from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile, is_zipfile

from docx import Document
from docx.oxml import parse_xml
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.knowledge.errors import ExtractionError
from app.knowledge.models import ExtractionSegment, ProcessingSource

MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 300
MAX_DOCX_ENTRIES = 2_000
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_DOCX_MEMBER_BYTES = 20 * 1024 * 1024
MAX_EXTRACTED_TEXT_CHARS = 1_100_000

_REQUIRED_DOCX_MEMBERS = frozenset({"[Content_Types].xml", "word/document.xml"})
_FORBIDDEN_DOCX_PREFIXES = ("word/activeX/", "word/embeddings/")


def extract_source(source: ProcessingSource, content: bytes | None) -> list[ExtractionSegment]:
    if source.source_type == "faq":
        if content is not None or not source.faq_question or not source.faq_answer:
            raise ExtractionError("malformed_document")
        return [
            ExtractionSegment(
                text=f"Question: {source.faq_question}\n\nAnswer: {source.faq_answer}",
                locator={"kind": "faq"},
            )
        ]

    if content is None or not source.original_filename or not source.mime_type:
        raise ExtractionError("malformed_document")
    if not content or len(content) > MAX_SOURCE_BYTES:
        raise ExtractionError("document_too_large" if content else "invalid_file_content")
    if source.byte_size is not None and len(content) != source.byte_size:
        raise ExtractionError("invalid_file_content")

    extension = source.original_filename.rsplit(".", maxsplit=1)[-1].lower()
    if extension == "pdf" and source.mime_type == "application/pdf":
        return extract_pdf(content)
    if (
        extension == "docx"
        and source.mime_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        return extract_docx(content)
    if extension in {"txt", "md"} and source.mime_type in {"text/plain", "text/markdown"}:
        return extract_text(content, kind="markdown" if extension == "md" else "text")
    raise ExtractionError("invalid_file_content")


def extract_pdf(content: bytes) -> list[ExtractionSegment]:
    if not content.startswith(b"%PDF-"):
        raise ExtractionError("invalid_file_content")
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise ExtractionError("encrypted_pdf")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ExtractionError("too_many_pages")
        segments = []
        extracted_characters = 0
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            extracted_characters += len(page_text)
            if extracted_characters > MAX_EXTRACTED_TEXT_CHARS:
                raise ExtractionError("document_too_large")
            segments.append(
                ExtractionSegment(
                    text=page_text,
                    locator={"kind": "pdf", "page_start": page_number, "page_end": page_number},
                )
            )
    except ExtractionError:
        raise
    except (PdfReadError, ValueError, TypeError, KeyError, OSError) as error:
        raise ExtractionError("malformed_document") from error
    except Exception as error:
        raise ExtractionError("extraction_failed") from error

    if not any(segment.text.strip() for segment in segments):
        raise ExtractionError("no_extractable_text")
    return segments


def _validate_docx_archive(content: bytes) -> None:
    if not is_zipfile(BytesIO(content)):
        raise ExtractionError("malformed_document")
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ENTRIES:
                raise ExtractionError("document_too_large")

            names = {entry.filename for entry in entries}
            if not _REQUIRED_DOCX_MEMBERS.issubset(names):
                raise ExtractionError("malformed_document")

            total_uncompressed = 0
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if (
                    entry.filename.startswith(("/", "\\"))
                    or "\\" in entry.filename
                    or ":" in path.parts[0]
                    or ".." in path.parts
                    or entry.flag_bits & 0x1
                ):
                    raise ExtractionError("malformed_document")
                if entry.file_size > MAX_DOCX_MEMBER_BYTES:
                    raise ExtractionError("document_too_large")
                total_uncompressed += entry.file_size
                if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise ExtractionError("document_too_large")
                if entry.filename == "word/vbaProject.bin" or entry.filename.startswith(
                    _FORBIDDEN_DOCX_PREFIXES
                ):
                    raise ExtractionError("invalid_file_content")
                if entry.filename.endswith((".xml", ".rels")):
                    with archive.open(entry) as xml_member:
                        xml_content = xml_member.read(MAX_DOCX_MEMBER_BYTES + 1)
                    if len(xml_content) > MAX_DOCX_MEMBER_BYTES:
                        raise ExtractionError("document_too_large")
                    original_xml = xml_content
                    xml_content = xml_content.upper()
                    if b"<!DOCTYPE" in xml_content or b"<!ENTITY" in xml_content:
                        raise ExtractionError("invalid_file_content")
                    if entry.filename.endswith(".rels") and (
                        b'TARGETMODE="EXTERNAL"' in xml_content
                        or b"TARGETMODE='EXTERNAL'" in xml_content
                    ):
                        raise ExtractionError("invalid_file_content")
                    # Lexical byte checks alone miss UTF-16 XML and whitespace
                    # around relationship attributes. python-docx's parser
                    # disables entity resolution and does not fetch network DTDs.
                    try:
                        root = parse_xml(original_xml)
                    except Exception as error:
                        raise ExtractionError("malformed_document") from error
                    if root.getroottree().docinfo.doctype or (
                        entry.filename.endswith(".rels")
                        and any(
                            element.get("TargetMode", "").strip().lower() == "external"
                            for element in root.iter()
                        )
                    ):
                        raise ExtractionError("invalid_file_content")
    except ExtractionError:
        raise
    except (BadZipFile, OSError, RuntimeError, ValueError) as error:
        raise ExtractionError("malformed_document") from error


def extract_docx(content: bytes) -> list[ExtractionSegment]:
    _validate_docx_archive(content)
    try:
        document = Document(BytesIO(content))
        segments = []
        extracted_characters = 0
        for block_index, block in enumerate(document.iter_inner_content(), start=1):
            if isinstance(block, Paragraph):
                text = block.text
            elif isinstance(block, Table):
                text = "\n".join("\t".join(cell.text for cell in row.cells) for row in block.rows)
            else:
                continue
            if text.strip():
                extracted_characters += len(text)
                if extracted_characters > MAX_EXTRACTED_TEXT_CHARS:
                    raise ExtractionError("document_too_large")
                segments.append(
                    ExtractionSegment(
                        text=text,
                        locator={
                            "kind": "docx",
                            "block_start": block_index,
                            "block_end": block_index,
                        },
                    )
                )
    except ExtractionError:
        raise
    except Exception as error:
        raise ExtractionError("malformed_document") from error

    if not segments:
        raise ExtractionError("no_extractable_text")
    return segments


def extract_text(content: bytes, kind: str) -> list[ExtractionSegment]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ExtractionError("unsupported_encoding") from error

    nul_count = decoded.count("\x00")
    suspicious_controls = sum(
        character < " " and character not in {"\n", "\r", "\t"} for character in decoded
    )
    if nul_count or (decoded and suspicious_controls / len(decoded) > 0.01):
        raise ExtractionError("invalid_file_content")

    lines = decoded.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments: list[ExtractionSegment] = []
    block_lines: list[str] = []
    block_start = 1

    def append_block(line_end: int) -> None:
        if block_lines:
            segments.append(
                ExtractionSegment(
                    text="\n".join(block_lines),
                    locator={
                        "kind": kind,
                        "line_start": block_start,
                        "line_end": line_end,
                    },
                )
            )
            block_lines.clear()

    for line_number, line in enumerate(lines, start=1):
        if line.strip():
            if not block_lines:
                block_start = line_number
            block_lines.append(line)
        else:
            append_block(line_number - 1)
    append_block(len(lines))

    if not segments:
        raise ExtractionError("no_extractable_text")
    return segments
