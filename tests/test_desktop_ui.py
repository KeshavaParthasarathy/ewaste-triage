import json
import pathlib
import re
import subprocess
from html.parser import HTMLParser


ROOT = pathlib.Path(__file__).parents[1]
STATIC = ROOT / "server" / "static"


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self._text = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self._text.append(data)

    @property
    def text(self):
        return " ".join(" ".join(self._text).split())


def _page():
    parser = PageParser()
    parser.feed(STATIC.joinpath("index.html").read_text())
    return parser


def _run_ui_contract(script):
    completed = subprocess.run(
        ["node", "-e", script, str(STATIC / "app.js")],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_desktop_page_is_accessible_and_self_contained():
    page = _page()
    assert all(text in page.text for text in (
        "New scan", "Use phone", "Recent scans", "Analyze another photo"
    ))
    assert sum(tag == "main" for tag, _ in page.elements) == 1
    assert not any(
        tag == "aside" and attrs.get("aria-label") == "Application sidebar"
        for tag, attrs in page.elements
    )
    assert any(tag == "details" for tag, _ in page.elements)
    assert "Why this result?" in page.text
    assert any(
        attrs.get("aria-live") == "polite" and attrs.get("role") == "status"
        for _, attrs in page.elements
    )
    assert "https://" not in page.text and "http://" not in page.text


def test_focused_workspace_keeps_assessment_in_the_scan_journey():
    page = _page()
    assert not any(
        tag == "nav" and attrs.get("aria-label") == "Primary"
        for tag, attrs in page.elements
    )
    assert any(
        tag == "section" and attrs.get("id") == "assessment-view"
        for tag, attrs in page.elements
    )


def test_photo_import_and_history_controls_have_keyboard_semantics():
    page = _page()
    controls = {attrs.get("id"): (tag, attrs) for tag, attrs in page.elements if attrs.get("id")}

    file_tag, file_attrs = controls["photo-input"]
    assert file_tag == "input" and file_attrs["type"] == "file"
    for file_type in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"):
        assert file_type in file_attrs["accept"]

    drop_tag, drop_attrs = controls["drop-target"]
    assert drop_tag == "label"
    assert drop_attrs["for"] == "photo-input"
    assert drop_attrs["role"] == "button"
    assert drop_attrs["tabindex"] == "0"

    assert controls["clear-history"][0] == "button"
    assert controls["analyze-another"][0] == "button"


def test_styles_define_responsive_reduced_motion_and_functional_states():
    css = STATIC.joinpath("app.css").read_text()
    assert "--motion-fast: 140ms" in css
    assert "--motion-standard: 220ms" in css
    assert "--motion-result: 300ms" in css
    assert 'data-state="classifying"' in css
    assert "transform: scale(0.985)" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "@media (max-width:" in css
    assert "transition: all" not in css


def test_scan_page_exposes_an_initially_closed_accessible_phone_pairing_sheet():
    page = _page()
    controls = {
        attrs.get("id"): (tag, attrs)
        for tag, attrs in page.elements
        if attrs.get("id")
    }

    assert "Use phone" in page.text
    assert controls["phone-capture"][1].get("aria-label") == "Use phone"
    dialog_tag, dialog_attrs = controls["phone-dialog"]
    assert dialog_tag == "dialog"
    assert "open" not in dialog_attrs
    assert dialog_attrs["aria-labelledby"] == "phone-dialog-title"
    assert controls["phone-qr"][0] == "img"
    assert controls["phone-qr"][1]["alt"]
    assert controls["phone-pairing-code"][0] in {"strong", "output"}
    assert controls["phone-countdown"][0] in {"span", "time"}
    assert controls["phone-stop"][0] == "button"
    assert controls["phone-incoming-result"][1].get("aria-live") == "polite"


def test_phone_pairing_copy_discloses_the_local_http_security_boundary():
    page = _page()

    assert "same-network HTTP" in page.text
    assert "not TLS" in page.text
    assert "memory-only capability URL" in page.text
    assert "six-digit code" in page.text
    assert "Pair securely" not in page.text


def test_clear_history_confirmation_is_short_and_direct():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
let message = null;
const accepted = UI.confirmClearHistory(value => {
  message = value;
  return true;
});
process.stdout.write(JSON.stringify({accepted, message}));
""")

    assert result == {
        "accepted": True,
        "message": "Delete all recent scans?",
    }


def test_phone_pairing_styles_use_staggered_functional_motion_and_reduced_motion():
    css = STATIC.joinpath("app.css").read_text()

    assert ".phone-dialog" in css
    assert 'data-phone-state="ready"' in css
    assert "40ms" in css
    assert "--phone-progress" in css
    reduced_motion = css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
    assert ".phone-pairing-reveal" in reduced_motion


def test_phone_pairing_sheet_closes_through_the_secure_escape_path():
    javascript = STATIC.joinpath("app.js").read_text()

    assert 'phoneDialog.addEventListener("keydown", event =>' in javascript
    assert 'if (event.key !== "Escape") return;' in javascript
    assert 'phoneDialog.addEventListener("close", () =>' in javascript
    assert "void controller.stopPhoneSession();" in javascript


def test_release_about_is_a_secondary_accessible_dialog_without_a_fourth_area():
    page = _page()
    controls = {
        attrs.get("id"): (tag, attrs)
        for tag, attrs in page.elements
        if attrs.get("id")
    }

    assert controls["open-release-about"][0] == "button"
    dialog_tag, dialog_attrs = controls["release-about-dialog"]
    assert dialog_tag == "dialog"
    assert dialog_attrs["aria-labelledby"] == "release-about-title"
    assert controls["release-about-close"][0] == "button"
    assert controls["release-about-status"][1]["aria-live"] == "polite"
    for target in (
        "release-app-version", "release-source-revision", "release-model-sha256",
        "release-component-sha256", "release-component-version",
    ):
        assert controls[target][0] == "output"
    navigation_links = [
        attrs for tag, attrs in page.elements
        if tag == "button" and attrs.get("data-view-link")
    ]
    assert not any(attrs.get("class") == "nav-item" for attrs in navigation_links)


def test_release_about_stagger_finishes_within_the_motion_budget():
    css = STATIC.joinpath("app.css").read_text()
    duration = int(re.search(
        r"release-detail-enter (\d+)ms", css
    ).group(1))
    delays = [int(value) for value in re.findall(
        r"release-about-details > div:nth-child\(\d+\) \{ animation-delay: (\d+)ms", css
    )]

    assert duration + max(delays) <= 325


def test_phone_controller_starts_polls_and_presents_incoming_result_once():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const requests = [];
const phoneStates = [];
const transitions = [];
const sections = [];
const scheduled = [];
let pollCount = 0;
const prediction = {
  scan_id: "phone-scan-1",
  class_name: "0301_computer_mouse",
  confidence: .93,
  low_confidence: false,
  topk: [{class_name: "0301_computer_mouse", confidence: .93}]
};
const view = {
  transition(state, payload) { transitions.push([state, payload && payload.scan_id]); },
  setBusy() {}, renderInfluence() {}, renderHistory() {}, markHistoryDeleting() {},
  clearPreview(message) { this.previewMessage = message; },
  showSection(name) { sections.push(name); },
  setPhoneState(state, payload) { phoneStates.push([state, payload && payload.pairing_code]); },
  updatePhoneSession(payload) { this.remaining = payload.expires_in_seconds; },
  renderPhoneIncomingResult(payload) { this.incoming = payload.scan_id; }
};
const fetchImpl = async (url, options = {}) => {
  requests.push([url, options.method || "GET"]);
  if (url === "/api/phone-session" && options.method === "POST") return {
    ok: true, status: 201,
    json: async () => ({active: true, pairing_code: "123456", expires_in_seconds: 600,
      upload_url: "http://192.168.1.42:49152/phone?token=secret", qr_png: "data:image/png;base64,eA=="})
  };
  if (url === "/api/phone-session" && (!options.method || options.method === "GET")) {
    pollCount += 1;
    return {ok: true, status: 200, json: async () => ({
      active: true, expires_in_seconds: 599, result: pollCount === 1 ? prediction : null
    })};
  }
  if (url === "/api/v1/history") return {ok: true, json: async () => []};
  if (url.startsWith("/api/v1/explain/")) return new Promise(() => {});
  throw new Error("unexpected request " + url);
};
const controller = UI.createController({
  view, fetchImpl,
  formDataFactory: () => ({append() {}}),
  nextFrame: async () => {}, objectUrl: () => "blob:none",
  schedule(callback, delay) { scheduled.push(delay); return {callback}; },
  cancelSchedule() {}
});
(async () => {
  const started = await controller.startPhoneSession();
  const first = await controller.pollPhoneSession();
  const second = await controller.pollPhoneSession();
  process.stdout.write(JSON.stringify({
    started, first, second, requests, phoneStates, transitions, sections, scheduled,
    incoming: view.incoming, remaining: view.remaining, previewMessage: view.previewMessage,
    assessment: controller.getAssessmentContext()
  }));
})();
""")

    assert result["started"] is True
    assert result["first"] is True
    assert result["second"] is True
    assert ["/api/phone-session", "POST"] in result["requests"]
    assert result["requests"].count(["/api/phone-session", "GET"]) == 2
    assert result["phoneStates"][:2] == [["starting", None], ["ready", "123456"]]
    assert result["transitions"] == [["result", "phone-scan-1"]]
    assert result["sections"] == ["scan"]
    assert result["incoming"] == "phone-scan-1"
    assert result["remaining"] == 599
    assert result["assessment"]["scan_id"] == "phone-scan-1"
    assert result["previewMessage"] == (
        "This photo arrived from your phone over temporary same-network HTTP. "
        "The full-resolution image was not retained."
    )
    assert 1000 in result["scheduled"]


def test_phone_controller_stop_revokes_server_and_ignores_stale_poll():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const requests = [];
const states = [];
let resolvePoll;
const view = {
  transition() {}, setBusy() {}, renderInfluence() {}, renderHistory() {}, markHistoryDeleting() {},
  setPhoneState(state) { states.push(state); }, updatePhoneSession() {}
};
const fetchImpl = async (url, options = {}) => {
  requests.push([url, options.method || "GET"]);
  if (url === "/api/phone-session" && options.method === "POST") return {
    ok: true, status: 201,
    json: async () => ({active: true, pairing_code: "123456", expires_in_seconds: 600,
      upload_url: "http://192.168.1.42:49152/phone?token=secret", qr_png: "data:image/png;base64,eA=="})
  };
  if (url === "/api/phone-session" && options.method === "GET") {
    return new Promise(resolve => { resolvePoll = resolve; });
  }
  if (url === "/api/phone-session" && options.method === "DELETE") return {
    ok: true, status: 200, json: async () => ({active: false, result: null})
  };
  if (url === "/api/v1/history") return {ok: true, json: async () => []};
  throw new Error("unexpected request " + url);
};
const controller = UI.createController({
  view, fetchImpl,
  formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => "",
  schedule: () => 1, cancelSchedule() {}
});
(async () => {
  await controller.startPhoneSession();
  const pending = controller.pollPhoneSession();
  await new Promise(resolve => setImmediate(resolve));
  const stopped = await controller.stopPhoneSession();
  resolvePoll({ok: true, status: 200, json: async () => ({active: false, result: null})});
  const stale = await pending;
  process.stdout.write(JSON.stringify({stopped, stale, requests, states}));
})();
""")

    assert result["stopped"] is True
    assert result["stale"] is False
    assert ["/api/phone-session", "DELETE"] in result["requests"]
    assert result["states"][-1] == "idle"


def test_release_about_controller_loads_the_closed_metadata_route_and_recovers():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const requests = [];
const states = [];
const values = [];
let call = 0;
const view = {
  setReleaseState(state, payload) { states.push(state); if (payload) values.push(payload); }
};
const fetchImpl = async url => {
  requests.push(url);
  call += 1;
  if (call === 2) return {ok: false, status: 503, json: async () => ({error: "temporarily unavailable"})};
  return {ok: true, status: 200, json: async () => ({
    app_version: "1.2.3", source_revision: "a".repeat(40),
    model_sha256: "b".repeat(64), component_database_sha256: "c".repeat(64),
    component_database_version: "2.0.0"
  })};
};
(async () => {
  const controller = UI.createReleaseAboutController({view, fetchImpl});
  const first = await controller.open();
  const failed = await controller.retry();
  const recovered = await controller.retry();
  process.stdout.write(JSON.stringify({first, failed, recovered, requests, states, values}));
})();
""")

    assert result["first"] is True
    assert result["failed"] is False
    assert result["recovered"] is True
    assert result["requests"] == [
        "/api/v1/release-metadata",
        "/api/v1/release-metadata",
        "/api/v1/release-metadata",
    ]
    assert result["states"] == ["loading", "ready", "loading", "error", "loading", "ready"]
    assert result["values"][-1]["component_database_version"] == "2.0.0"


def test_release_about_controller_deduplicates_rapid_opens_and_ignores_closed_request():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const states = [];
let resolve;
const pending = new Promise(done => { resolve = done; });
let requests = 0;
const controller = UI.createReleaseAboutController({
  view: {setReleaseState(state) { states.push(state); }},
  fetchImpl: async () => { requests += 1; return pending; }
});
(async () => {
  const first = controller.open();
  const duplicate = controller.open();
  controller.close();
  resolve({ok: true, status: 200, json: async () => ({
    app_version: "1.2.3", source_revision: "a".repeat(40), model_sha256: "b".repeat(64),
    component_database_sha256: "c".repeat(64), component_database_version: "2.0.0"
  })});
  process.stdout.write(JSON.stringify({first: await first, duplicate: await duplicate, requests, states}));
})();
""")

    assert result == {
        "first": False,
        "duplicate": False,
        "requests": 1,
        "states": ["loading"],
    }


def test_release_about_dom_view_renders_literal_values_and_native_close_paths():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const nodes = new Map();
function node(id = "") {
  const handlers = {};
  return {
    id, handlers, dataset: {}, style: {setProperty() {}}, hidden: false, textContent: "",
    value: "", files: [], children: [], className: "", open: false,
    append(...items) { this.children.push(...items); }, appendChild(item) { this.children.push(item); return item; },
    replaceChildren(...items) { this.children = items; }, setAttribute(name, value) { this[name] = String(value); },
    removeAttribute(name) { delete this[name]; }, querySelector() { return node(); }, querySelectorAll() { return []; },
    addEventListener(name, handler) { handlers[name] = handler; }, focus() { this.focused = (this.focused || 0) + 1; },
    showModal() { this.open = true; }, close() { this.open = false; if (handlers.close) handlers.close(); },
    closest(selector) {
      if (selector.includes("#" + this.id)) return this;
      if (selector.includes("[data-view-link]") && this.dataset.viewLink) return this;
      if (selector.includes("[data-phone-action]") && this.dataset.phoneAction) return this;
      return null;
    }
  };
}
const documentHandlers = {};
const document = {
  readyState: "complete", documentElement: node("html"), handlers: documentHandlers,
  getElementById(id) { if (!nodes.has(id)) nodes.set(id, node(id)); return nodes.get(id); },
  querySelector() { return node(); }, querySelectorAll() { return []; }, createElement() { return node(); },
  addEventListener(name, handler) { documentHandlers[name] = handler; }
};
global.fetch = async url => {
  if (url === "/api/v1/history") return {ok: true, status: 200, json: async () => []};
  if (url === "/api/v1/reference/categories") return {ok: true, status: 200, json: async () => [
    {category_id: "0306_mobile_phone", display_name: "Mobile phone"}
  ]};
  if (url === "/api/v1/scans/assessment-scan/assessment") return {
    ok: false, status: 409, json: async () => ({error: "confirm category"})
  };
  if (url === "/api/v1/reference/categories/0306_mobile_phone") return {ok: true, status: 200, json: async () => ({
    category_id: "0306_mobile_phone", display_name: "Mobile phone", template_version: "2.0.0",
    components: [], rules: [], handling_note: ""
  })};
  return {ok: true, status: 200, json: async () => ({
    app_version: "<img src=x onerror=1>", source_revision: "a".repeat(40), model_sha256: "b".repeat(64),
    component_database_sha256: "c".repeat(64), component_database_version: "2.0.0"
  })};
};
global.FormData = class { entries() { return []; } append() {} };
global.URL = {createObjectURL: () => "blob:none", revokeObjectURL() {}};
global.requestAnimationFrame = callback => callback();
global.confirm = () => false;
const controller = UI.bootstrap(document);
const opener = document.getElementById("open-release-about");
controller.openHistory({
  scan_id: "assessment-scan",
  prediction: {class_name: "0306_mobile_phone", confidence: .91, low_confidence: false, topk: []},
  confirmation: {accepted_class_name: "0306_mobile_phone", source: "user"}
});
controller.openAssessment().then(() => {
  document.getElementById("assessment-age-min").value = "24";
  document.getElementById("assessment-issue-notes").value = "draft stays editable";
  document.getElementById("assessment-issue-overheating").checked = true;
  controller.markAssessmentEditing();
  document.getElementById("phone-dialog").dataset.phoneState = "ready";
  documentHandlers.click({target: opener, preventDefault() {}});
  setImmediate(() => {
  const dialog = document.getElementById("release-about-dialog");
  const literal = document.getElementById("release-app-version").textContent;
  const assessmentForm = document.getElementById("assessment-form");
  const snapshot = () => [
    document.getElementById("assessment-view").hidden,
    document.getElementById("assessment-frame").dataset.assessmentState,
    document.getElementById("assessment-age-min").value,
    document.getElementById("assessment-issue-notes").value,
    document.getElementById("assessment-issue-overheating").checked,
    document.getElementById("phone-dialog").dataset.phoneState
  ];
  const editAge = value => {
    const control = document.getElementById("assessment-age-min");
    control.value = value;
    assessmentForm.handlers.input({target: control});
  };
  documentHandlers.click({target: document.getElementById("release-about-close-secondary"), preventDefault() {}});
  const afterButton = snapshot();
  editAge("25");
  const buttonFocus = opener.focused;
  dialog.showModal();
  dialog.handlers.click({target: dialog});
  const afterBackdrop = snapshot();
  editAge("26");
  const backdropFocus = opener.focused;
  dialog.showModal();
  dialog.handlers.keydown({key: "Escape", preventDefault() {}});
  const afterEscape = snapshot();
  const notes = document.getElementById("assessment-issue-notes");
  notes.value = "draft remains usable after every close";
  assessmentForm.handlers.input({target: notes});
  process.stdout.write(JSON.stringify({literal, afterButton, afterBackdrop, afterEscape, finalNotes: notes.value, buttonFocus, backdropFocus, escapeFocus: opener.focused, open: dialog.open, controller: Boolean(controller)}));
  });
});
""")

    assert result == {
        "literal": "<img src=x onerror=1>",
        "afterButton": [False, "assessment-editing", "24", "draft stays editable", True, "ready"],
        "afterBackdrop": [False, "assessment-editing", "25", "draft stays editable", True, "ready"],
        "afterEscape": [False, "assessment-editing", "26", "draft stays editable", True, "ready"],
        "finalNotes": "draft remains usable after every close",
        "buttonFocus": 1,
        "backdropFocus": 2,
        "escapeFocus": 3,
        "open": False,
        "controller": True,
    }


def test_controller_runs_real_states_once_and_loads_influence_asynchronously():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const states = [];
const busy = [];
const requests = [];
const entries = [];
let resultPayload;
let influence;
let resolveClassification;
const classification = new Promise(resolve => { resolveClassification = resolve; });
const view = {
  transition(state, payload) { states.push(state); if (state === 'result') resultPayload = payload; },
  setBusy(value) { busy.push(value); },
  showPreview() {},
  renderInfluence(payload) { influence = payload; },
  renderHistory() {},
  markHistoryDeleting() {}
};
const fetchImpl = async (url, options = {}) => {
  requests.push([url, options.method || 'GET']);
  if (url === '/api/v1/classify') return classification;
  if (url.startsWith('/api/v1/explain/')) return {
    ok: true,
    json: async () => ({grid_size: 2, values: [[0, 1], [.5, .25]], copy: 'Regions influenced this result; not a physical diagnosis.'})
  };
  if (url === '/api/v1/history') return {ok: true, json: async () => []};
  throw new Error('unexpected request ' + url);
};
class TestFormData { append(name, value, filename) { entries.push([name, filename || value]); } }
const controller = UI.createController({
  view,
  fetchImpl,
  formDataFactory: () => new TestFormData(),
  nextFrame: async () => {},
  objectUrl: () => 'blob:preview'
});
const file = {name: 'device.heic', type: 'image/heic'};
const first = controller.analyze(file);
const second = controller.analyze(file);
resolveClassification({
  ok: true,
  json: async () => ({scan_id: 'scan-7', class_name: '0306_mobile_phone', confidence: .91, low_confidence: false, topk: []})
});
Promise.all([first, second]).then(async ([firstAccepted, secondAccepted]) => {
  await new Promise(resolve => setImmediate(resolve));
  process.stdout.write(JSON.stringify({states, busy, requests, entries, resultPayload, influence, firstAccepted, secondAccepted}));
});
""")

    assert result["states"] == ["decoding", "classifying", "result"]
    assert result["busy"] == [True, False]
    assert result["firstAccepted"] is True
    assert result["secondAccepted"] is False
    assert result["entries"] == [["image", "device.heic"]]
    assert result["resultPayload"]["class_name"] == "0306_mobile_phone"
    assert result["influence"]["values"][0][1] == 1
    assert result["requests"].count(["/api/v1/classify", "POST"]) == 1
    assert ["/api/v1/explain/scan-7", "POST"] in result["requests"]


def test_stale_classification_success_cannot_replace_an_open_history_record():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const states = [];
const busy = [];
const requests = [];
let resolveClassification;
const classification = new Promise(resolve => { resolveClassification = resolve; });
const view = {
  transition(state, payload = {}) { states.push([state, payload.scan_id || null]); },
  setBusy(value) { busy.push(value); },
  showPreview() {}, clearPreview() {}, showSection() {},
  renderInfluence() {}, renderHistory() {}, markHistoryDeleting() {}
};
const fetchImpl = async (url) => {
  requests.push(url);
  if (url === '/api/v1/classify') return classification;
  if (url === '/api/v1/history') return {ok: true, json: async () => []};
  if (url.startsWith('/api/v1/explain/')) return new Promise(() => {});
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({
  view, fetchImpl,
  formDataFactory: () => ({append() {}}),
  nextFrame: async () => {},
  objectUrl: () => 'blob:pending'
});
(async () => {
  const pending = controller.analyze({name: 'pending.jpg', type: 'image/jpeg'});
  await new Promise(resolve => setImmediate(resolve));
  controller.openHistory({
    scan_id: 'history-A',
    prediction: {class_name: '0301_keyboard', confidence: .77, low_confidence: false, topk: []}
  });
  const busyBeforeResolve = busy.slice();
  resolveClassification({
    ok: true,
    json: async () => ({scan_id: 'late-B', class_name: '0306_mobile_phone', confidence: .9, low_confidence: false, topk: []})
  });
  await pending;
  await new Promise(resolve => setImmediate(resolve));
  process.stdout.write(JSON.stringify({
    states, busy, busyBeforeResolve, requests,
    assessment: controller.getAssessmentContext()
  }));
})();
""")

    assert result["states"] == [
        ["decoding", None],
        ["classifying", None],
        ["result", "history-A"],
    ]
    assert result["busyBeforeResolve"] == [True, False]
    assert result["busy"] == [True, False]
    assert result["assessment"]["scan_id"] == "history-A"
    assert "/api/v1/explain/late-B" not in result["requests"]


def test_stale_classification_error_cannot_end_busy_state_for_a_newer_analysis():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const states = [];
const busy = [];
const classifications = [];
function deferredResponse() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
}
const view = {
  transition(state, payload = {}) { states.push([state, payload.scan_id || payload.message || null]); },
  setBusy(value) { busy.push(value); },
  showPreview() {}, reset() {},
  renderInfluence() {}, renderHistory() {}, markHistoryDeleting() {}
};
const fetchImpl = async (url) => {
  if (url === '/api/v1/classify') {
    const deferred = deferredResponse();
    classifications.push(deferred);
    return deferred.promise;
  }
  if (url === '/api/v1/history') return {ok: true, json: async () => []};
  if (url.startsWith('/api/v1/explain/')) return new Promise(() => {});
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({
  view, fetchImpl,
  formDataFactory: () => ({append() {}}),
  nextFrame: async () => {},
  objectUrl: file => 'blob:' + file.name
});
(async () => {
  const first = controller.analyze({name: 'a.jpg', type: 'image/jpeg'});
  await new Promise(resolve => setImmediate(resolve));
  controller.reset();
  const second = controller.analyze({name: 'b.jpg', type: 'image/jpeg'});
  await new Promise(resolve => setImmediate(resolve));
  const secondStarted = classifications.length === 2;
  classifications[0].resolve({
    ok: false, status: 503, json: async () => ({error: 'late failure from A'})
  });
  await first;
  await new Promise(resolve => setImmediate(resolve));
  const busyBeforeSecondResolve = busy.slice();
  if (secondStarted) {
    classifications[1].resolve({
      ok: true,
      json: async () => ({scan_id: null, class_name: '0303_laptop', confidence: .8, low_confidence: false, topk: []})
    });
  }
  await second;
  process.stdout.write(JSON.stringify({states, busy, busyBeforeSecondResolve, secondStarted}));
})();
""")

    assert result["secondStarted"] is True
    assert result["states"] == [
        ["decoding", None],
        ["classifying", None],
        ["empty", None],
        ["decoding", None],
        ["classifying", None],
        ["result", None],
    ]
    assert result["busyBeforeSecondResolve"] == [True, False, True]
    assert result["busy"] == [True, False, True, False]


def test_controller_ignores_an_explanation_from_an_older_active_scan():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const influenceRenders = [];
const explanations = {};
let classificationCount = 0;
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderHistory() {},
  markHistoryDeleting() {},
  renderInfluence(payload) { influenceRenders.push(payload.scan_id || payload.error); }
};
function deferredResponse() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
}
const fetchImpl = async (url) => {
  if (url === '/api/v1/classify') {
    classificationCount += 1;
    const scan = classificationCount === 1 ? 'scan-A' : 'scan-B';
    return {ok: true, json: async () => ({scan_id: scan, class_name: '0306_mobile_phone', confidence: .9, low_confidence: false, topk: []})};
  }
  if (url.startsWith('/api/v1/explain/')) {
    const scan = url.split('/').pop();
    explanations[scan] = deferredResponse();
    return explanations[scan].promise;
  }
  if (url === '/api/v1/history') return {ok: true, json: async () => []};
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({
  view, fetchImpl,
  formDataFactory: () => ({append() {}}),
  nextFrame: async () => {},
  objectUrl: file => 'blob:' + file.name
});
(async () => {
  await controller.analyze({name: 'a.jpg', type: 'image/jpeg'});
  await controller.analyze({name: 'b.jpg', type: 'image/jpeg'});
  explanations['scan-B'].resolve({ok: true, json: async () => ({scan_id: 'scan-B', values: [[1]]})});
  await new Promise(resolve => setImmediate(resolve));
  explanations['scan-A'].resolve({ok: false, status: 503, json: async () => ({error: 'explanation unavailable'})});
  await new Promise(resolve => setImmediate(resolve));
  process.stdout.write(JSON.stringify({influenceRenders}));
})();
""")

    assert result["influenceRenders"] == ["scan-B"]


def test_history_review_clears_the_current_scan_preview_before_showing_another_record():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
let preview = null;
let influenceMessage = null;
const cleared = [];
const shownResults = [];
const view = {
  transition(state, payload = {}) {
    if (state === 'result' || state === 'review') {
      shownResults.push({scan_id: payload.scan_id, class_name: payload.class_name, preview});
    }
  },
  setBusy() {},
  showPreview(url) { preview = url; },
  clearPreview(message) { preview = null; cleared.push(message); },
  renderInfluence(payload) { influenceMessage = payload.error || null; },
  renderHistory() {}, markHistoryDeleting() {}, showSection() {}
};
const fetchImpl = async (url) => {
  if (url === '/api/v1/classify') return {
    ok: true,
    json: async () => ({scan_id: 'scan-B', class_name: '0306_mobile_phone', confidence: .9, low_confidence: false, topk: []})
  };
  if (url === '/api/v1/history') return {ok: true, json: async () => []};
  if (url.startsWith('/api/v1/explain/')) return new Promise(() => {});
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({
  view, fetchImpl,
  formDataFactory: () => ({append() {}}),
  nextFrame: async () => {},
  objectUrl: file => 'blob:' + file.name
});
(async () => {
  await controller.analyze({name: 'scan-b.jpg', type: 'image/jpeg'});
  controller.openHistory({
    scan_id: 'scan-A',
    prediction: {class_name: '0301_keyboard', confidence: .77, low_confidence: false, topk: []}
  });
  process.stdout.write(JSON.stringify({preview, cleared, shownResults, influenceMessage}));
})();
""")

    assert result["preview"] is None
    assert result["cleared"] == [
        "The source image is unavailable for this history record."
    ]
    assert result["influenceMessage"] == (
        "The source image is unavailable for this history record. "
        "Model influence is available only immediately after a new classification."
    )
    assert result["shownResults"][-1] == {
        "scan_id": "scan-A",
        "class_name": "0301_keyboard",
        "preview": None,
    }


def test_alternative_selection_preserves_model_evidence_and_confirms_assessment_category():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
let chooseAlternative;
const corrections = [];
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {},
  showSection() {}, clearPreview() {},
  renderHistory() {}, markHistoryDeleting() {},
  setAlternativeHandler(handler) { chooseAlternative = handler; },
  renderCorrection(payload) { corrections.push(payload); }
};
const fetchImpl = async (url) => {
  if (url === '/api/v1/classify') return {
    ok: true,
    json: async () => ({
      scan_id: null,
      class_name: '0306_mobile_phone',
      confidence: .82,
      low_confidence: false,
      topk: [
        {class_name: '0306_mobile_phone', confidence: .82},
        {class_name: '0303_laptop', confidence: .12}
      ]
    })
  };
  if (url === '/api/v1/history') return {ok: true, json: async () => []};
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({
  view, fetchImpl,
  formDataFactory: () => ({append() {}}),
  nextFrame: async () => {},
  objectUrl: () => 'blob:scan'
});
(async () => {
  await controller.analyze({name: 'scan.jpg', type: 'image/jpeg'});
  if (typeof chooseAlternative !== 'function' || typeof controller.getAssessmentContext !== 'function') {
    process.stdout.write(JSON.stringify({connected: false}));
    return;
  }
  chooseAlternative({class_name: '0303_laptop', confidence: .12});
  process.stdout.write(JSON.stringify({
    connected: true,
    correction: corrections[0],
    assessment: controller.getAssessmentContext()
  }));
})();
""")

    assert result["connected"] is True
    assert result["correction"] == {
        "scan_id": None,
        "model_class_name": "0306_mobile_phone",
        "model_confidence": 0.82,
        "confirmed_class_name": "0303_laptop",
        "confirmed_confidence": 0.12,
        "confirmation_source": "user",
    }
    assert result["assessment"] == {
        "scan_id": None,
        "confirmed_class_name": "0303_laptop",
        "model_evidence": {
            "class_name": "0306_mobile_phone",
            "confidence": 0.82,
        },
        "confirmation": {
            "source": "user",
            "selected_model_score": 0.12,
        },
    }


def test_controller_routes_low_confidence_and_failures_to_honest_states():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const stateSets = [];
function controllerFor(response) {
  const states = [];
  const view = {
    transition(state, payload) { states.push([state, payload.message || null]); },
    setBusy() {}, showPreview() {}, renderInfluence() {}, renderHistory() {}, markHistoryDeleting() {}
  };
  return [UI.createController({
    view,
    fetchImpl: async () => response,
    formDataFactory: () => ({append() {}}),
    nextFrame: async () => {},
    objectUrl: () => 'blob:preview'
  }), states];
}
(async () => {
  let pair = controllerFor({ok: true, json: async () => ({scan_id: null, class_name: '0303_laptop', confidence: .41, low_confidence: true, topk: []})});
  await pair[0].analyze({name: 'uncertain.webp', type: 'image/webp'});
  stateSets.push(pair[1]);

  pair = controllerFor({ok: false, status: 400, json: async () => ({error: 'uploaded file is not a decodable image'})});
  await pair[0].analyze({name: 'broken.png', type: 'image/png'});
  stateSets.push(pair[1]);

  const formats = ['photo.jpg', 'photo.jpeg', 'photo.png', 'photo.webp', 'photo.heic'].map(name => UI.isSupportedImage({name, type: ''}));
  process.stdout.write(JSON.stringify({stateSets, formats}));
})();
""")

    assert [state for state, _ in result["stateSets"][0]] == [
        "decoding", "classifying", "review"
    ]
    assert [state for state, _ in result["stateSets"][1]] == [
        "decoding", "classifying", "error"
    ]
    assert result["stateSets"][1][-1][1] == "uploaded file is not a decodable image"
    assert result["formats"] == [True, True, True, True, True]


def test_controller_lists_deletes_and_clears_history_through_versioned_api():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const requests = [];
const renders = [];
let records = [
  {scan_id: 'new', created_at: '2026-09-05T12:00:00Z', prediction: {class_name: '0306_mobile_phone', confidence: .9}},
  {scan_id: 'old', created_at: '2026-09-04T12:00:00Z', prediction: {class_name: '0301_keyboard', confidence: .8}}
];
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {},
  renderHistory(items) { renders.push(items.map(item => item.scan_id)); },
  markHistoryDeleting(id) { renders.push(['deleting', id]); }
};
const fetchImpl = async (url, options = {}) => {
  requests.push([url, options.method || 'GET']);
  if (url === '/api/v1/history' && options.method === 'DELETE') { records = []; return {ok: true, json: async () => ({deleted_count: 1})}; }
  if (url === '/api/v1/history/old' && options.method === 'DELETE') { records = records.filter(item => item.scan_id !== 'old'); return {ok: true, json: async () => ({deleted: true})}; }
  if (url === '/api/v1/history') return {ok: true, json: async () => records};
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => ''});
(async () => {
  await controller.loadHistory();
  await controller.deleteHistory('old');
  await controller.clearHistory();
  process.stdout.write(JSON.stringify({requests, renders}));
})();
""")

    assert result["requests"] == [
        ["/api/v1/history", "GET"],
        ["/api/v1/history/old", "DELETE"],
        ["/api/v1/history", "GET"],
        ["/api/v1/history", "DELETE"],
        ["/api/v1/history", "GET"],
    ]
    assert result["renders"] == [
        ["new", "old"],
        ["deleting", "old"],
        ["new"],
        [],
    ]


def test_history_fetches_ignore_stale_responses_and_corrections_are_persisted():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const renders = [], requests = [];
let first, second;
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {},
  showSection() {}, clearPreview() {},
  renderHistory(records) { renders.push(records.map(row => row.scan_id)); },
  renderCorrection() {}
};
const fetchImpl = (url, options = {}) => {
  requests.push([url, options.method || 'GET']);
  if (url === '/api/v1/history' && !first) return new Promise(resolve => { first = resolve; });
  if (url === '/api/v1/history') return new Promise(resolve => { second = resolve; });
  if (url === '/api/v1/history/scan-1/confirmation') return Promise.resolve({ok: true, json: async () => ({})});
};
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => ''});
(async () => {
  const older = controller.loadHistory();
  const newer = controller.loadHistory();
  await new Promise(resolve => setImmediate(resolve));
  second({ok: true, json: async () => [{scan_id: 'new'}]});
  await newer;
  first({ok: true, json: async () => [{scan_id: 'old'}]});
  await older;
  controller.openHistory({scan_id: 'scan-1', prediction: {class_name: '0306_mobile_phone', confidence: .9, topk: [{class_name: '0306_mobile_phone', confidence: .9}, {class_name: '0303_laptop', confidence: .1}]}});
  controller.selectAlternative({class_name: '0303_laptop'});
  await new Promise(resolve => setImmediate(resolve));
  process.stdout.write(JSON.stringify({renders, requests}));
})();
""")

    assert result["renders"] == [["new"]]
    assert ["/api/v1/history/scan-1/confirmation", "PUT"] in result["requests"]


def test_history_row_uses_confirmed_category_and_retains_original_model_evidence():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
process.stdout.write(JSON.stringify(UI.historyPresentation({
  scan_id: 'corrected', created_at: '2026-09-05T12:00:00Z',
  prediction: {class_name: '0306_mobile_phone', confidence: .91},
  confirmation: {accepted_class_name: '0303_laptop', source: 'user'}
})));
""")

    assert result["category"] == "Laptop"
    assert result["model_evidence"] == "Original model: Mobile phone · 91% confidence"


def test_rapid_corrections_are_serialized_and_pending_choices_are_coalesced():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const requests = [], corrections = [];
let resolveFirst, resolveLast;
const prediction = {
  class_name: '0306_mobile_phone', confidence: .91,
  topk: [
    {class_name: '0306_mobile_phone', confidence: .91},
    {class_name: '0303_laptop', confidence: .05},
    {class_name: '0301_computer_mouse', confidence: .03},
    {class_name: '0301_keyboard', confidence: .01}
  ]
};
const record = category => ({
  scan_id: 'ordered-scan', prediction,
  confirmation: {accepted_class_name: category, source: 'user'}
});
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {}, renderHistory() {},
  markHistoryDeleting() {}, showSection() {}, clearPreview() {},
  renderCorrection(value) { corrections.push(value.confirmed_class_name); },
  renderHistoryError(message) { corrections.push(message); }
};
const fetchImpl = (url, options = {}) => {
  if (url === '/api/v1/history/ordered-scan/confirmation') {
    const category = JSON.parse(options.body).accepted_class_name;
    requests.push(category);
    if (requests.length === 1) {
      return new Promise(resolve => { resolveFirst = () => resolve({ok: true, json: async () => record(category)}); });
    }
    return new Promise(resolve => { resolveLast = () => resolve({ok: true, json: async () => record(category)}); });
  }
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({
  view, fetchImpl, formDataFactory: () => ({append() {}}),
  nextFrame: async () => {}, objectUrl: () => ''
});
(async () => {
  controller.openHistory({scan_id: 'ordered-scan', prediction});
  controller.selectAlternative({class_name: '0303_laptop'});
  controller.selectAlternative({class_name: '0301_computer_mouse'});
  controller.selectAlternative({class_name: '0301_keyboard'});
  await new Promise(resolve => setImmediate(resolve));
  const beforeFirstSettles = [...requests];
  resolveFirst();
  await new Promise(resolve => setImmediate(resolve));
  const afterFirstSettles = [...requests];
  resolveLast();
  await new Promise(resolve => setImmediate(resolve));
  process.stdout.write(JSON.stringify({
    beforeFirstSettles, afterFirstSettles, corrections,
    finalCategory: controller.getAssessmentContext().confirmed_class_name
  }));
})();
""")

    assert result["beforeFirstSettles"] == ["0303_laptop"]
    assert result["afterFirstSettles"] == [
        "0303_laptop",
        "0301_keyboard",
    ]
    assert result["corrections"][-1] == "0301_keyboard"
    assert result["finalCategory"] == "0301_keyboard"


def test_newer_correction_supersedes_an_inflight_assessment_save_confirmation():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const requests = [];
let resolveSaveConfirmation, resolveLatestConfirmation;
const prediction = {
  class_name: '0306_mobile_phone', confidence: .91,
  topk: [
    {class_name: '0306_mobile_phone', confidence: .91},
    {class_name: '0303_laptop', confidence: .05},
    {class_name: '0301_keyboard', confidence: .04}
  ]
};
const categories = prediction.topk.map(item => ({category_id: item.class_name}));
const template = {category_id: '0306_mobile_phone', display_name: 'Mobile phone', template_version: '1.0.0', components: [], rules: []};
const record = category => ({
  scan_id: 'mixed-scan', prediction,
  confirmation: {accepted_class_name: category, source: 'user'}
});
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {}, renderHistory() {},
  markHistoryDeleting() {}, showSection() {}, clearPreview() {}, renderCorrection() {},
  setAssessmentState() {}, setAssessmentBusy() {}, clearAssessmentFormError() {},
  showAssessmentFormError() {}, renderAssessmentDraft() {}, renderAssessment() {},
  readAssessmentForm() { return {age_months: null, cycle_count: null, usage: 'unknown', condition: 'unknown', operational: 'working', known_issues: {}, component_overrides: {}}; },
  getAssessmentCategory() { return '0303_laptop'; }
};
const fetchImpl = (url, options = {}) => {
  const method = options.method || 'GET';
  requests.push([url, method, options.body ? JSON.parse(options.body) : null]);
  if (url === '/api/v1/reference/categories') return Promise.resolve({ok: true, json: async () => categories});
  if (url === '/api/v1/scans/mixed-scan/assessment' && method === 'GET') {
    return Promise.resolve({ok: false, status: 409, json: async () => ({error: 'confirm category'})});
  }
  if (url === '/api/v1/reference/categories/0306_mobile_phone') {
    return Promise.resolve({ok: true, json: async () => template});
  }
  if (url === '/api/v1/history/mixed-scan/confirmation') {
    const category = JSON.parse(options.body).accepted_class_name;
    if (category === '0303_laptop') {
      return new Promise(resolve => { resolveSaveConfirmation = () => resolve({ok: true, json: async () => record(category)}); });
    }
    return new Promise(resolve => { resolveLatestConfirmation = () => resolve({ok: true, json: async () => record(category)}); });
  }
  if (url === '/api/v1/scans/mixed-scan/assessment' && method === 'PUT') {
    return Promise.resolve({ok: true, json: async () => ({category_id: '0303_laptop'})});
  }
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => ''});
(async () => {
  controller.openHistory({scan_id: 'mixed-scan', prediction});
  await controller.openAssessment();
  const save = controller.saveAssessment({});
  await new Promise(resolve => setImmediate(resolve));
  controller.selectAlternative({class_name: '0301_keyboard'});
  resolveSaveConfirmation();
  const saved = await save;
  await new Promise(resolve => setImmediate(resolve));
  resolveLatestConfirmation();
  await new Promise(resolve => setImmediate(resolve));
  process.stdout.write(JSON.stringify({saved, requests, context: controller.getAssessmentContext()}));
})();
""")

    assert result["saved"] is False
    assert [
        request[2]["accepted_class_name"]
        for request in result["requests"]
        if request[0].endswith("/confirmation")
    ] == ["0303_laptop", "0301_keyboard"]
    assert not any(
        request[0].endswith("/assessment") and request[1] == "PUT"
        for request in result["requests"]
    )
    assert result["context"]["confirmed_class_name"] == "0301_keyboard"


def test_stale_save_confirmation_failure_is_suppressed_for_newer_correction():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const requests = [], formErrors = [], historyErrors = [];
let failSaveConfirmation, resolveLatestConfirmation;
const prediction = {
  class_name: '0306_mobile_phone', confidence: .91,
  topk: [
    {class_name: '0306_mobile_phone', confidence: .91},
    {class_name: '0303_laptop', confidence: .05},
    {class_name: '0301_keyboard', confidence: .04}
  ]
};
const categories = prediction.topk.map(item => ({category_id: item.class_name}));
const template = {category_id: '0306_mobile_phone', display_name: 'Mobile phone', template_version: '1.0.0', components: [], rules: []};
const record = category => ({scan_id: 'failed-mixed-scan', prediction, confirmation: {accepted_class_name: category, source: 'user'}});
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {}, renderHistory() {},
  markHistoryDeleting() {}, showSection() {}, clearPreview() {}, renderCorrection() {},
  setAssessmentState() {}, setAssessmentBusy() {}, clearAssessmentFormError() {},
  showAssessmentFormError(message) { formErrors.push(message); },
  renderHistoryError(message) { historyErrors.push(message); },
  renderAssessmentDraft() {}, renderAssessment() {},
  readAssessmentForm() { return {age_months: null, cycle_count: null, usage: 'unknown', condition: 'unknown', operational: 'working', known_issues: {}, component_overrides: {}}; },
  getAssessmentCategory() { return '0303_laptop'; }
};
const fetchImpl = (url, options = {}) => {
  const method = options.method || 'GET';
  requests.push([url, method, options.body ? JSON.parse(options.body) : null]);
  if (url === '/api/v1/reference/categories') return Promise.resolve({ok: true, json: async () => categories});
  if (url === '/api/v1/scans/failed-mixed-scan/assessment' && method === 'GET') {
    return Promise.resolve({ok: false, status: 409, json: async () => ({error: 'confirm category'})});
  }
  if (url === '/api/v1/reference/categories/0306_mobile_phone') return Promise.resolve({ok: true, json: async () => template});
  if (url === '/api/v1/history/failed-mixed-scan/confirmation') {
    const category = JSON.parse(options.body).accepted_class_name;
    if (category === '0303_laptop') {
      return new Promise(resolve => { failSaveConfirmation = () => resolve({ok: false, status: 503, json: async () => ({error: 'old save failed'})}); });
    }
    return new Promise(resolve => { resolveLatestConfirmation = () => resolve({ok: true, json: async () => record(category)}); });
  }
  if (url === '/api/v1/scans/failed-mixed-scan/assessment' && method === 'PUT') {
    throw new Error('obsolete assessment PUT');
  }
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => ''});
(async () => {
  controller.openHistory({scan_id: 'failed-mixed-scan', prediction});
  await controller.openAssessment();
  const save = controller.saveAssessment({});
  await new Promise(resolve => setImmediate(resolve));
  controller.selectAlternative({class_name: '0301_keyboard'});
  failSaveConfirmation();
  const saved = await save;
  await new Promise(resolve => setImmediate(resolve));
  resolveLatestConfirmation();
  await new Promise(resolve => setImmediate(resolve));
  process.stdout.write(JSON.stringify({saved, requests, formErrors, historyErrors, context: controller.getAssessmentContext()}));
})();
""")

    assert result["saved"] is False
    assert result["formErrors"] == []
    assert result["historyErrors"] == []
    assert not any(
        request[0].endswith("/assessment") and request[1] == "PUT"
        for request in result["requests"]
    )
    assert result["context"]["confirmed_class_name"] == "0301_keyboard"


def test_failed_latest_confirmation_restores_and_renders_last_committed_category():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const corrections = [], errors = [];
const prediction = {
  class_name: '0306_mobile_phone', confidence: .9,
  topk: [
    {class_name: '0306_mobile_phone', confidence: .9},
    {class_name: '0303_laptop', confidence: .06},
    {class_name: '0301_keyboard', confidence: .04}
  ]
};
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {}, renderHistory() {},
  markHistoryDeleting() {}, showSection() {}, clearPreview() {},
  renderCorrection(value) { corrections.push(value.confirmed_class_name); },
  renderHistoryError(message) { errors.push(message); }
};
const fetchImpl = () => Promise.resolve({
  ok: false, status: 503, json: async () => ({error: 'disk unavailable'})
});
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => ''});
(async () => {
  controller.openHistory({
    scan_id: 'failed-scan', prediction,
    confirmation: {accepted_class_name: '0303_laptop', source: 'user'}
  });
  controller.selectAlternative({class_name: '0301_keyboard'});
  await new Promise(resolve => setImmediate(resolve));
  process.stdout.write(JSON.stringify({corrections, errors, context: controller.getAssessmentContext()}));
})();
""")

    assert result["corrections"] == ["0301_keyboard", "0303_laptop"]
    assert len(result["errors"]) == 1
    assert "not saved" in result["errors"][0]
    assert result["context"]["confirmed_class_name"] == "0303_laptop"


def test_latest_confirmation_success_converges_after_same_scan_history_reopen():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const corrections = [];
let settle;
const prediction = {
  class_name: '0306_mobile_phone', confidence: .9,
  topk: [
    {class_name: '0306_mobile_phone', confidence: .9},
    {class_name: '0303_laptop', confidence: .1}
  ]
};
const staleRecord = {scan_id: 'same-scan', prediction};
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {}, renderHistory() {},
  markHistoryDeleting() {}, showSection() {}, clearPreview() {},
  renderCorrection(value) { corrections.push(value.confirmed_class_name); }
};
const fetchImpl = () => new Promise(resolve => {
  settle = () => resolve({ok: true, json: async () => ({
    ...staleRecord,
    confirmation: {accepted_class_name: '0303_laptop', source: 'user'}
  })});
});
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => ''});
(async () => {
  controller.openHistory(staleRecord);
  controller.selectAlternative({class_name: '0303_laptop'});
  controller.openHistory(staleRecord);
  settle();
  await new Promise(resolve => setImmediate(resolve));
  process.stdout.write(JSON.stringify({corrections, context: controller.getAssessmentContext()}));
})();
""")

    assert result["corrections"] == ["0303_laptop", "0303_laptop"]
    assert result["context"]["confirmed_class_name"] == "0303_laptop"


def test_reset_suppresses_obsolete_confirmation_error_reporting():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const errors = [];
let settle;
const prediction = {
  class_name: '0306_mobile_phone', confidence: .9,
  topk: [{class_name: '0306_mobile_phone', confidence: .9}, {class_name: '0303_laptop', confidence: .1}]
};
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {}, renderHistory() {},
  markHistoryDeleting() {}, showSection() {}, clearPreview() {}, renderCorrection() {}, reset() {},
  renderHistoryError(message) { errors.push(message); }
};
const fetchImpl = () => new Promise(resolve => { settle = resolve; });
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => ''});
(async () => {
  controller.openHistory({scan_id: 'stale-scan', prediction});
  controller.selectAlternative({class_name: '0303_laptop'});
  controller.reset();
  settle({ok: false, status: 503, json: async () => ({error: 'late failure'})});
  await new Promise(resolve => setImmediate(resolve));
  process.stdout.write(JSON.stringify({errors}));
})();
""")

    assert result["errors"] == []


def test_reset_suppresses_obsolete_confirmation_success_rendering():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const corrections = [];
let settle;
const prediction = {
  class_name: '0306_mobile_phone', confidence: .9,
  topk: [{class_name: '0306_mobile_phone', confidence: .9}, {class_name: '0303_laptop', confidence: .1}]
};
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {}, renderHistory() {},
  markHistoryDeleting() {}, showSection() {}, clearPreview() {}, reset() {},
  renderCorrection(value) { corrections.push(value.confirmed_class_name); }
};
const fetchImpl = () => new Promise(resolve => {
  settle = () => resolve({ok: true, json: async () => ({
    scan_id: 'reset-scan', prediction,
    confirmation: {accepted_class_name: '0303_laptop', source: 'user'}
  })});
});
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => ''});
(async () => {
  controller.openHistory({scan_id: 'reset-scan', prediction});
  controller.selectAlternative({class_name: '0303_laptop'});
  controller.reset();
  settle();
  await new Promise(resolve => setImmediate(resolve));
  process.stdout.write(JSON.stringify({corrections, context: controller.getAssessmentContext()}));
})();
""")

    assert result["corrections"] == ["0303_laptop"]
    assert result["context"] is None


def test_delete_waits_for_and_cancels_confirmation_writer_before_removal():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const requests = [], corrections = [];
let settleConfirmation;
const prediction = {
  class_name: '0306_mobile_phone', confidence: .9,
  topk: [{class_name: '0306_mobile_phone', confidence: .9}, {class_name: '0303_laptop', confidence: .1}]
};
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {}, renderHistory() {},
  markHistoryDeleting() {}, showSection() {}, clearPreview() {},
  renderCorrection(value) { corrections.push(value.confirmed_class_name); }
};
const fetchImpl = (url, options = {}) => {
  requests.push([url, options.method || 'GET']);
  if (url.endsWith('/confirmation')) {
    return new Promise(resolve => { settleConfirmation = () => resolve({ok: true, json: async () => ({scan_id: 'delete-scan', prediction, confirmation: {accepted_class_name: '0303_laptop', source: 'user'}})}); });
  }
  if (url === '/api/v1/history/delete-scan') return Promise.resolve({ok: true, json: async () => ({deleted: true})});
  if (url === '/api/v1/history') return Promise.resolve({ok: true, json: async () => []});
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => '', undoDelay: 0});
(async () => {
  controller.openHistory({scan_id: 'delete-scan', prediction});
  controller.selectAlternative({class_name: '0303_laptop'});
  const deletion = controller.deleteHistory('delete-scan');
  await new Promise(resolve => setImmediate(resolve));
  const beforeSettle = [...requests];
  settleConfirmation();
  await deletion;
  process.stdout.write(JSON.stringify({beforeSettle, requests, corrections}));
})();
""")

    assert result["beforeSettle"] == [
        ["/api/v1/history/delete-scan/confirmation", "PUT"]
    ]
    assert result["requests"] == [
        ["/api/v1/history/delete-scan/confirmation", "PUT"],
        ["/api/v1/history/delete-scan", "DELETE"],
        ["/api/v1/history", "GET"],
    ]
    assert result["corrections"] == ["0303_laptop"]


def test_history_delete_invalidates_an_inflight_list_before_commit():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
let stale;
const renders = [];
const view = {transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {}, markHistoryDeleting() {}, renderHistory(rows) { renders.push(rows.map(row => row.scan_id)); }};
let getCount = 0;
const fetchImpl = (url, options = {}) => {
  if (url === '/api/v1/history' && !options.method && getCount++ === 0) return new Promise(resolve => { stale = resolve; });
  if (url === '/api/v1/history') return Promise.resolve({ok: true, json: async () => []});
  if (url === '/api/v1/history/old') return Promise.resolve({ok: true, json: async () => ({deleted: true})});
};
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => '', undoDelay: 0});
(async () => {
  const delayed = controller.loadHistory();
  await new Promise(resolve => setImmediate(resolve));
  await controller.deleteHistory('old');
  stale({ok: true, json: async () => [{scan_id: 'old'}]});
  await delayed;
  process.stdout.write(JSON.stringify({renders}));
})();
""")

    assert result["renders"] == [[]]
