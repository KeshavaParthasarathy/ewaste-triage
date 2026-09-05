import json
import pathlib
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
        "Scan", "Phone capture", "History", "Analyze another photo"
    ))
    assert any(tag == "main" for tag, _ in page.elements)
    assert any(
        tag == "nav" and attrs.get("aria-label") == "Primary"
        for tag, attrs in page.elements
    )
    assert any(
        attrs.get("aria-live") == "polite" and attrs.get("role") == "status"
        for _, attrs in page.elements
    )
    assert "https://" not in page.text and "http://" not in page.text


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
