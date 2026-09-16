from app.ai.triage.models import TriageErrorCode


class TriageAgentError(Exception):
    def __init__(self, code: TriageErrorCode) -> None:
        self.code = code
        super().__init__("Support triage could not be completed safely.")
