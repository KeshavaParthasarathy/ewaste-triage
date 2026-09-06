import json
import pathlib
import subprocess
from html.parser import HTMLParser


ROOT = pathlib.Path(__file__).parents[1]
STATIC = ROOT / "server" / "static"
INDEX = STATIC / "index.html"
CSS = STATIC / "app.css"
JS = STATIC / "app.js"


class AssessmentParser(HTMLParser):
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
    parser = AssessmentParser()
    parser.feed(INDEX.read_text())
    return parser


def _run_ui_contract(script):
    completed = subprocess.run(
        ["node", "-e", script, str(JS)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_assessment_ui_labels_estimates_and_evidence():
    page = _page()
    for text in (
        "Device assessment",
        "Evidence used",
        "Components and next steps",
        "Category-based inventory",
        "Unknown",
        "Correct identification",
    ):
        assert text in page.text
    assert "not a measured health reading" in page.text


def test_assessment_form_exposes_supported_item_and_component_inputs():
    page = _page()
    controls = {
        attrs.get("id"): (tag, attrs)
        for tag, attrs in page.elements
        if attrs.get("id")
    }

    form_tag, form_attrs = controls["assessment-form"]
    assert form_tag == "form"
    assert form_attrs.get("novalidate") is None
    assert controls["assessment-view"][1]["tabindex"] == "-1"
    assert controls["assessment-category"][0] == "select"
    for control_id in (
        "assessment-age-min",
        "assessment-age-max",
        "assessment-cycles-min",
        "assessment-cycles-max",
    ):
        tag, attrs = controls[control_id]
        assert tag == "input" and attrs["type"] == "number"
        assert attrs["min"] == "0"
    for control_id in (
        "assessment-usage",
        "assessment-condition",
        "assessment-operational",
    ):
        assert controls[control_id][0] == "select"
    assert controls["save-assessment"][0] == "button"
    assert controls["assessment-components"][1]["aria-live"] == "off"


def test_safety_guidance_precedes_component_recommendations_in_reading_order():
    html = INDEX.read_text()
    assert html.index('id="assessment-safety"') < html.index('id="assessment-components"')


def test_assessment_motion_has_responsive_reduced_motion_fallback_and_bounded_reveal():
    css = CSS.read_text()
    assert "data-assessment-state" in css
    for state in (
        "assessment-loading",
        "assessment-editing",
        "assessment-ready",
        "assessment-error",
    ):
        assert state in css
    assert "--assessment-stagger: 35ms" in css
    assert "animation-delay: 105ms" in css
    assert "@media (max-width: 760px)" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "transition: all" not in css


def test_assessment_payload_uses_only_task3_fields_and_authorized_overrides():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const payload = UI.assessmentPayloadFromValues({
  age_min: '24', age_max: '36', cycle_min: '200', cycle_max: '400',
  usage: 'heavy', condition: 'visible_wear', operational: 'intermittent',
  'component.lithium_ion_battery.presence': 'standard',
  'component.lithium_ion_battery.condition': 'damaged',
  'component.lithium_ion_battery.lifecycle_metric': 'cycles',
  'component.lithium_ion_battery.lifecycle_min': '700',
  'component.lithium_ion_battery.lifecycle_max': '900',
  'component.logic_board.presence': ''
});
process.stdout.write(JSON.stringify(payload));
""")

    assert result == {
        "age_months": {"minimum": 24, "maximum": 36},
        "cycle_count": {"minimum": 200, "maximum": 400},
        "usage": "heavy",
        "condition": "visible_wear",
        "operational": "intermittent",
        "component_overrides": {
            "lithium_ion_battery": {
                "presence_label": "standard",
                "condition": "damaged",
                "lifecycle": {"metric": "cycles", "minimum": 700, "maximum": 900},
            }
        },
    }


def test_assessment_presentation_keeps_ranges_units_unknowns_and_provenance_honest():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const presentation = UI.buildAssessmentPresentation({
  template_version: '1.0.0',
  template: {
    category_id: '0306_mobile_phone', display_name: 'Mobile phone',
    handling_note: 'Potential context only.',
    rules: [{text: 'Use a battery collection option.', source_ids: ['epa-battery'], reviewed_on: '2026-09-05'}]
  },
  inputs: {age_months: {minimum: 24, maximum: 36}, cycle_count: {minimum: 200, maximum: 400}},
  components: [
    {
      component_id: 'battery', display_name: 'Battery', presence_label: 'standard', safety_sensitive: true,
      lifecycle: {metric: 'cycles_to_capacity', minimum: 800, maximum: 800, capacity_percent: 80,
                  source_ids: ['eu-phone']},
      source_ids: ['eu-phone'], evidence_grade: 'regulatory_minimum', reviewed_on: '2026-09-05',
      result: {percent_used: {minimum: 25, maximum: 50}, confidence: 'moderate', recommendation: 'diagnostic_test',
               reasons: ['Test before reuse.'], evidence: [{kind: 'cycle_count', detail: 'User-reported cycles: 200–400.', source_ids: []}]}
    },
    {
      component_id: 'camera', display_name: 'Camera', presence_label: 'common', lifecycle: null,
      result: {percent_used: null, confidence: 'unavailable', recommendation: 'unknown',
               reasons: ['No supported lifecycle reference is available for this component.'], evidence: []}
    }
  ]
});
process.stdout.write(JSON.stringify(presentation));
""")

    assert result["overall_range"] == "25–50% used"
    assert result["components"][0]["range"] == "25–50% used"
    assert result["components"][0]["reference_range"] == "800 cycles to 80% capacity"
    assert result["components"][0]["source_label"] == "eu-phone · regulatory minimum · reviewed 2026-09-05"
    assert result["components"][1]["range"] == "Unknown"
    assert "reviewed component lifecycle reference" in result["components"][1]["missing_guidance"]
    assert result["safety"][0]["source_label"] == "epa-battery · reviewed 2026-09-05"
    assert result["input_evidence"] == [
        {"label": "Age", "value": "24–36 months"},
        {"label": "Cycles", "value": "200–400 cycles"},
        {"label": "Usage", "value": "Unknown"},
        {"label": "Visible condition", "value": "Unknown"},
        {"label": "Operating state", "value": "Unknown"},
    ]


def test_controller_loads_draft_then_confirms_and_saves_without_unhandled_promises():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const states = [], requests = [], drafts = [], renders = [], busy = [];
const categories = [{category_id: '0306_mobile_phone', display_name: 'Mobile phone'}];
const template = {category_id: '0306_mobile_phone', display_name: 'Mobile phone', template_version: '1.0.0', components: [], rules: []};
const saved = {scan_id: 'scan-7', category_id: '0306_mobile_phone', template_version: '1.0.0', template,
               inputs: {usage: 'unknown', condition: 'unknown', operational: 'unknown', age_months: null, cycle_count: null},
               component_overrides: {}, components: []};
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {}, renderHistory() {}, markHistoryDeleting() {},
  showSection(section) { states.push(['section', section]); },
  setAssessmentState(state, message) { states.push([state, message || null]); },
  setAssessmentBusy(value) { busy.push(value); },
  renderAssessmentDraft(value) { drafts.push(value); },
  renderAssessment(value) { renders.push(value); },
  readAssessmentForm() { return {age_months: null, cycle_count: null, usage: 'unknown', condition: 'unknown', operational: 'working', component_overrides: {}}; },
  getAssessmentCategory() { return '0306_mobile_phone'; }
};
const fetchImpl = async (url, options = {}) => {
  requests.push([url, options.method || 'GET', typeof options.body === 'string' ? JSON.parse(options.body) : null]);
  if (url === '/api/v1/classify') return {ok: true, json: async () => ({scan_id: 'scan-7', class_name: '0306_mobile_phone', confidence: .91, low_confidence: false, topk: []})};
  if (url === '/api/v1/history') return {ok: true, json: async () => []};
  if (url === '/api/v1/reference/categories') return {ok: true, json: async () => categories};
  if (url === '/api/v1/scans/scan-7/assessment' && !options.method) return {ok: false, status: 409, json: async () => ({error: 'confirm category'})};
  if (url === '/api/v1/reference/categories/0306_mobile_phone') return {ok: true, json: async () => template};
  if (url === '/api/v1/history/scan-7/confirmation') return {ok: true, json: async () => ({confirmation: {source: 'user'}})};
  if (url === '/api/v1/scans/scan-7/assessment' && options.method === 'PUT') return {ok: true, json: async () => saved};
  if (url.startsWith('/api/v1/explain/')) return new Promise(() => {});
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => 'blob:test'});
(async () => {
  await controller.analyze({name: 'phone.jpg', type: 'image/jpeg'});
  await controller.openAssessment();
  const firstSave = controller.saveAssessment({});
  const secondSave = await controller.saveAssessment({});
  const firstSaved = await firstSave;
  process.stdout.write(JSON.stringify({states, requests, drafts: drafts.length, renders: renders.length, busy, firstSaved, secondSave}));
})();
""")

    assert result["drafts"] == 1
    assert result["renders"] == 1
    assert result["firstSaved"] is True
    assert result["secondSave"] is False
    assert result["busy"] == [True, False]
    assert [state[0] for state in result["states"]] == [
        "section",
        "assessment-loading",
        "assessment-editing",
        "assessment-loading",
        "assessment-ready",
    ]
    methods = [(url, method) for url, method, _ in result["requests"]]
    assert ("/api/v1/history/scan-7/confirmation", "PUT") in methods
    assert methods.count(("/api/v1/scans/scan-7/assessment", "PUT")) == 1


def test_stale_assessment_response_cannot_replace_a_newer_scan_and_errors_are_final():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const states = [], renders = [];
let resolveCategories;
const delayedCategories = new Promise(resolve => { resolveCategories = resolve; });
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {}, renderHistory() {}, markHistoryDeleting() {},
  showSection() {}, clearPreview() {},
  setAssessmentState(state, message) { states.push([state, message || null]); },
  setAssessmentBusy() {}, renderAssessment(value) { renders.push(value.scan_id); }, renderAssessmentDraft() {}
};
const fetchImpl = async (url) => {
  if (url === '/api/v1/history') return {ok: true, json: async () => []};
  if (url === '/api/v1/reference/categories') return delayedCategories;
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => ''});
(async () => {
  controller.openHistory({scan_id: 'scan-A', prediction: {class_name: '0301_keyboard', confidence: .8, topk: []}});
  const pending = controller.openAssessment();
  controller.openHistory({scan_id: 'scan-B', prediction: {class_name: '0306_mobile_phone', confidence: .9, topk: []}});
  resolveCategories({ok: false, status: 503, json: async () => ({error: 'late database failure'})});
  const opened = await pending;
  process.stdout.write(JSON.stringify({states, renders, opened, context: controller.getAssessmentContext()}));
})();
""")

    assert result["opened"] is False
    assert result["renders"] == []
    assert result["states"] == [["assessment-loading", None]]
    assert result["context"]["scan_id"] == "scan-B"


def test_changing_a_draft_category_preserves_entered_device_facts():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const drafts = [];
const facts = {age_months: {minimum: 24, maximum: 30}, cycle_count: null, usage: 'heavy', condition: 'visible_wear', operational: 'working', component_overrides: {}};
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {}, renderHistory() {}, markHistoryDeleting() {},
  showSection() {}, clearPreview() {}, setAssessmentState() {}, setAssessmentBusy() {},
  renderAssessmentDraft(value) { drafts.push(value); },
  readAssessmentForm() { return facts; }
};
const templates = {
  '0306_mobile_phone': {category_id: '0306_mobile_phone', display_name: 'Mobile phone', components: [], rules: []},
  '0303_laptop': {category_id: '0303_laptop', display_name: 'Laptop', components: [], rules: []}
};
const fetchImpl = async (url) => {
  if (url === '/api/v1/history') return {ok: true, json: async () => []};
  if (url === '/api/v1/reference/categories') return {ok: true, json: async () => Object.values(templates).map(({category_id, display_name}) => ({category_id, display_name}))};
  if (url === '/api/v1/scans/scan-A/assessment') return {ok: false, status: 409, json: async () => ({error: 'confirm category'})};
  const category = url.split('/').pop();
  if (templates[category]) return {ok: true, json: async () => templates[category]};
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => ''});
(async () => {
  controller.openHistory({scan_id: 'scan-A', prediction: {class_name: '0306_mobile_phone', confidence: .9, topk: []}});
  await controller.openAssessment();
  await controller.changeAssessmentCategory('0303_laptop');
  process.stdout.write(JSON.stringify({drafts: drafts.map(value => ({category: value.template.category_id, inputs: value.draft_inputs || null}))}));
})();
""")

    assert result["drafts"] == [
        {"category": "0306_mobile_phone", "inputs": None},
        {
            "category": "0303_laptop",
            "inputs": {
                "age_months": {"minimum": 24, "maximum": 30},
                "cycle_count": None,
                "usage": "heavy",
                "condition": "visible_wear",
                "operational": "working",
                "component_overrides": {},
            },
        },
    ]
