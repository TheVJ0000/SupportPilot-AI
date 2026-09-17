/* SupportPilot V1: dependency-free launcher; all customer state stays in the iframe. */
(function () {
  'use strict';
  var script = document.currentScript;
  var marker = '__supportpilotWidgetV1';
  var state = window[marker] || (window[marker] = { warned: false });
  function warn() {
    if (!state.warned) {
      state.warned = true;
      console.warn('SupportPilot: invalid or conflicting widget configuration.');
    }
  }
  if (!script) { warn(); return; }
  var publicId = (script.getAttribute('data-supportpilot-public-id') || '').trim();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(publicId)) {
    warn(); return;
  }
  var source;
  try { source = new URL(script.src); } catch { warn(); return; }
  if (!/^https?:$/.test(source.protocol) || source.username || source.password) { warn(); return; }
  publicId = publicId.toLowerCase();
  if (state.publicId) {
    if (state.publicId !== publicId || state.origin !== source.origin) warn();
    return;
  }
  state.publicId = publicId;
  state.origin = source.origin;
  var label = (script.getAttribute('data-supportpilot-label') || '').trim().slice(0, 40) || 'Support';
  var position = script.getAttribute('data-supportpilot-position') === 'left' ? 'left' : 'right';

  function mount() {
    var root = document.createElement('div');
    root.id = 'supportpilot-widget-root';
    // Inline important properties protect the one light-DOM boundary from broad host CSS.
    root.style.setProperty('all', 'initial', 'important');
    root.style.setProperty('position', 'fixed', 'important');
    root.style.setProperty('bottom', '16px', 'important');
    root.style.setProperty(position, '16px', 'important');
    root.style.setProperty('z-index', '2147483000', 'important');
    var shadow = root.attachShadow({ mode: 'open' });
    var style = document.createElement('style');
    style.textContent = ':host{font-family:system-ui,sans-serif;color:#0f172a}*{box-sizing:border-box}' +
      'button{font:600 14px/1.4 system-ui,sans-serif;cursor:pointer;border:0}' +
      'button:focus-visible{outline:3px solid #67e8f9;outline-offset:3px}' +
      '.launcher{padding:15px 22px;border-radius:999px;background:#0e7490;color:white;box-shadow:0 8px 30px #0f172a40}' +
      '.panel{position:absolute;bottom:64px;width:min(400px,calc(100vw - 32px));height:min(640px,calc(100dvh - 112px));' +
      'max-height:calc(100vh - 112px);min-height:0;border:1px solid #cbd5e1;border-radius:18px;overflow:hidden;' +
      'background:#f8fafc;box-shadow:0 12px 48px #0f172a40;display:flex;flex-direction:column}' +
      '.panel[hidden]{display:none}.bar{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:#0f172a;color:white}' +
      '.bar span{font:600 13px system-ui,sans-serif}.close{background:transparent;color:white;padding:5px 8px;border-radius:6px}' +
      'iframe{display:block;border:0;width:100%;min-height:0;flex:1;background:#f8fafc}';
    var launcher = document.createElement('button');
    launcher.type = 'button';
    launcher.className = 'launcher';
    launcher.textContent = label;
    launcher.setAttribute('aria-expanded', 'false');
    launcher.setAttribute('aria-controls', 'supportpilot-panel');
    var panel = document.createElement('section');
    panel.id = 'supportpilot-panel';
    panel.className = 'panel';
    panel.style[position] = '0';
    panel.hidden = true;
    panel.setAttribute('aria-label', 'Support chat panel');
    var bar = document.createElement('div');
    bar.className = 'bar';
    var title = document.createElement('span');
    title.textContent = 'SupportPilot · Support';
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'close';
    close.textContent = 'Close';
    close.setAttribute('aria-label', 'Close support chat');
    bar.append(title, close);
    panel.append(bar);
    var iframe;
    function hide() {
      panel.hidden = true;
      launcher.setAttribute('aria-expanded', 'false');
      launcher.focus();
    }
    launcher.addEventListener('click', function () {
      if (!panel.hidden) { hide(); return; }
      if (!iframe) {
        iframe = document.createElement('iframe');
        iframe.title = 'Support chat';
        iframe.setAttribute('sandbox', 'allow-scripts allow-forms allow-same-origin');
        iframe.referrerPolicy = 'no-referrer';
        iframe.src = source.origin + '/embed/' + publicId;
        panel.append(iframe);
      }
      panel.hidden = false;
      launcher.setAttribute('aria-expanded', 'true');
      close.focus();
    });
    close.addEventListener('click', hide);
    shadow.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !panel.hidden) { event.preventDefault(); hide(); }
    });
    shadow.append(style, panel, launcher);
    document.body.append(root);
  }
  if (document.body) mount();
  else document.addEventListener('DOMContentLoaded', mount, { once: true });
}());
