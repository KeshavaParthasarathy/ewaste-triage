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
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


FAKE_DOM = r"""
class FakeNode {
  constructor(tag = 'div', id = '') {
    this.tagName = String(tag).toUpperCase();
    this.id = id;
    this.children = [];
    this.attributes = {};
    this.dataset = {};
    this.listeners = {};
    this.style = {values: {}, setProperty: (name, value) => { this.style.values[name] = value; }};
    this.className = '';
    this.value = '';
    this.name = '';
    this.hidden = false;
    this.disabled = false;
    this.textContent = '';
    this.focused = false;
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(type, handler) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(handler);
  }
  dispatch(type) {
    for (const handler of this.listeners[type] || []) handler({target: this});
  }
  focus() { this.focused = true; }
  matches(selector) {
    if (selector.startsWith('.')) return this.className.split(/\s+/).includes(selector.slice(1));
    return this.tagName.toLowerCase() === selector.toLowerCase();
  }
  querySelectorAll(selector) {
    const found = [];
    const visit = node => {
      for (const child of node.children || []) {
        if (child.matches && child.matches(selector)) found.push(child);
        visit(child);
      }
    };
    visit(this);
    return found;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
class FakeDocument {
  constructor() {
    this.nodes = new Map();
    this.documentElement = new FakeNode('html', 'html');
    this.imageStage = new FakeNode('div');
    this.imageStage.className = 'image-stage';
  }
  createElement(tag) { return new FakeNode(tag); }
  getElementById(id) {
    if (!this.nodes.has(id)) this.nodes.set(id, new FakeNode('div', id));
    return this.nodes.get(id);
  }
  querySelector(selector) { return selector === '.image-stage' ? this.imageStage : null; }
  querySelectorAll() { return []; }
}
function walk(root) {
  const found = [];
  const visit = node => {
    found.push(node);
    for (const child of node.children || []) visit(child);
  };
  visit(root);
  return found;
}
"""


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
    for control_id in (
        "assessment-issue-overheating",
        "assessment-issue-odor",
        "assessment-issue-swelling",
        "assessment-issue-recall",
    ):
        tag, attrs = controls[control_id]
        assert tag == "input"
        assert attrs["type"] == "checkbox"
    notes_tag, notes_attrs = controls["assessment-issue-notes"]
    assert notes_tag == "textarea"
    assert "maxlength" not in notes_attrs
    assert notes_attrs["data-max-code-points"] == "500"
    assert controls["assessment-safety-list"][1]["aria-live"] == "polite"
    assert controls["save-assessment"][0] == "button"
    feedback_tag, feedback_attrs = controls["assessment-save-feedback"]
    assert feedback_tag == "p"
    assert feedback_attrs["role"] == "alert"
    assert feedback_attrs["tabindex"] == "-1"
    assert "hidden" in feedback_attrs
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


def test_phone_width_header_has_a_dedicated_overflow_guard():
    css = CSS.read_text()
    compact = css.split("@media (max-width: 380px)", 1)[1]
    assert ".brand > span:last-child" in compact
    assert ".sidebar" in compact
    assert ".nav-item" in compact


def test_assessment_payload_uses_closed_known_issues_and_authorized_overrides():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const payload = UI.assessmentPayloadFromValues({
  age_min: '24', age_max: '36', cycle_min: '200', cycle_max: '400',
  usage: 'heavy', condition: 'visible_wear', operational: 'intermittent',
  issue_overheating: 'true', issue_odor: undefined,
  issue_swelling_or_battery_damage: 'on', issue_recall: false,
  issue_notes: ' Fan clicks after ten minutes. ',
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
        "known_issues": {
            "overheating": True,
            "odor": False,
            "swelling_or_battery_damage": True,
            "recall": False,
            "notes": "Fan clicks after ten minutes.",
        },
        "component_overrides": {
            "lithium_ion_battery": {
                "presence_label": "standard",
                "condition": "damaged",
                "lifecycle": {"metric": "cycles", "minimum": 700, "maximum": 900},
            }
        },
    }


def test_known_issue_notes_are_bounded_before_submit():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
try {
  UI.assessmentPayloadFromValues({issue_notes: 'x'.repeat(501)});
  process.stdout.write(JSON.stringify({error: null}));
} catch (error) {
  process.stdout.write(JSON.stringify({error: error.message}));
}
""")

    assert "500" in result["error"]


def test_known_issue_notes_bound_counts_unicode_code_points():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
function attempt(note) {
  try { return {notes: UI.assessmentPayloadFromValues({issue_notes: note}).known_issues.notes}; }
  catch (error) { return {error: error.message}; }
}
process.stdout.write(JSON.stringify({accepted: attempt('😀'.repeat(500)), rejected: attempt('😀'.repeat(501))}));
""")

    assert result["accepted"]["notes"] == "😀" * 500
    assert "500" in result["rejected"]["error"]


def test_known_issue_notes_control_validity_counts_astral_characters_as_code_points():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const control = {
  value: '', message: null, attributes: {},
  setCustomValidity(message) { this.message = message; },
  setAttribute(name, value) { this.attributes[name] = String(value); },
  removeAttribute(name) { delete this.attributes[name]; }
};
control.value = '😀'.repeat(500);
const accepted = UI.validateKnownIssueNotesControl(control);
const acceptedState = {message: control.message, invalid: control.attributes['aria-invalid'] || null};
control.value = '😀'.repeat(501);
const rejected = UI.validateKnownIssueNotesControl(control);
process.stdout.write(JSON.stringify({accepted, acceptedState, rejected, message: control.message, invalid: control.attributes['aria-invalid']}));
""")

    assert result["accepted"] is True
    assert result["acceptedState"] == {"message": "", "invalid": None}
    assert result["rejected"] is False
    assert "500" in result["message"]
    assert result["invalid"] == "true"


def test_lifecycle_payload_supports_capacity_and_clears_disabled_dependents():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
function attempt(values) {
  try { return {payload: UI.assessmentPayloadFromValues(values)}; }
  catch (error) { return {error: error.message}; }
}
const base = {usage: 'unknown', condition: 'unknown', operational: 'unknown'};
const capacity = attempt({...base,
  'component.battery.lifecycle_metric': 'cycles_to_capacity',
  'component.battery.lifecycle_min': '700',
  'component.battery.lifecycle_max': '900',
  'component.battery.lifecycle_capacity': '80'
});
const cleared = attempt({...base,
  'component.battery.presence': 'standard',
  'component.battery.lifecycle_metric': '',
  'component.battery.lifecycle_min': '700',
  'component.battery.lifecycle_max': '900',
  'component.battery.lifecycle_capacity': '80'
});
const missingCapacity = attempt({...base,
  'component.battery.lifecycle_metric': 'cycles_to_capacity',
  'component.battery.lifecycle_min': '700',
  'component.battery.lifecycle_max': '900'
});
const invalidCapacity = attempt({...base,
  'component.battery.lifecycle_metric': 'cycles_to_capacity',
  'component.battery.lifecycle_min': '700',
  'component.battery.lifecycle_max': '900',
  'component.battery.lifecycle_capacity': '101'
});
const yearsIgnoreCapacity = attempt({...base,
  'component.battery.lifecycle_metric': 'years',
  'component.battery.lifecycle_min': '4',
  'component.battery.lifecycle_max': '6',
  'component.battery.lifecycle_capacity': '80'
});
process.stdout.write(JSON.stringify({capacity, cleared, missingCapacity, invalidCapacity, yearsIgnoreCapacity}));
""")

    assert result["capacity"]["payload"]["component_overrides"] == {
        "battery": {
            "lifecycle": {
                "metric": "cycles_to_capacity",
                "minimum": 700,
                "maximum": 900,
                "capacity_percent": 80,
            }
        }
    }
    assert result["cleared"]["payload"]["component_overrides"] == {
        "battery": {"presence_label": "standard"}
    }
    assert "capacity" in result["missingCapacity"]["error"].lower()
    assert "1 to 100" in result["invalidCapacity"]["error"]
    assert result["yearsIgnoreCapacity"]["payload"]["component_overrides"] == {
        "battery": {
            "lifecycle": {"metric": "years", "minimum": 4, "maximum": 6}
        }
    }


def test_existing_capacity_lifecycle_override_round_trips_through_dom_and_can_clear():
    result = _run_ui_contract(FAKE_DOM + r"""
const UI = require(process.argv[1]);
const document = new FakeDocument();
const view = UI.createDomView(document);
const lifecycle = {metric: 'cycles_to_capacity', minimum: 700, maximum: 900, capacity_percent: 80};
const component = {
  component_id: 'battery', display_name: 'Battery', presence_label: 'standard', safety_sensitive: true,
  lifecycle: {...lifecycle, source_ids: [], evidence_grade: 'user_provided_unverified', reviewed_on: null},
  source_ids: ['immutable-safety-source'], evidence_grade: 'regulatory', reviewed_on: '2026-09-05',
  result: {percent_used: null, confidence: 'unavailable', recommendation: 'unknown', reasons: ['More facts are needed.'], evidence: []}
};
const assessment = {
  scan_id: 'scan-capacity', category_id: '0306_mobile_phone', template_version: '1.0.0',
  template: {category_id: '0306_mobile_phone', display_name: 'Mobile phone', template_version: '1.0.0', components: [component], rules: []},
  inputs: {age_months: null, cycle_count: null, usage: 'unknown', condition: 'unknown', operational: 'unknown'},
  component_overrides: {battery: {lifecycle}}, components: [component]
};
view.renderAssessment({
  assessment,
  categories: [{category_id: '0306_mobile_phone', display_name: 'Mobile phone'}],
  context: {model_evidence: {class_name: '0306_mobile_phone', confidence: .91}, confirmation: {source: 'user'}},
});
const nodes = walk(document.getElementById('assessment-components'));
const named = name => nodes.find(node => node.name === name);
const metric = named('component.battery.lifecycle_metric');
const minimum = named('component.battery.lifecycle_min');
const maximum = named('component.battery.lifecycle_max');
const capacity = named('component.battery.lifecycle_capacity');
const enabledValues = () => Object.fromEntries(
  [metric, minimum, maximum, capacity]
    .filter(node => node && !node.disabled)
    .map(node => [node.name, node.value])
);
const before = {
  metricOptions: metric.children.map(option => option.value),
  values: [metric.value, minimum.value, maximum.value, capacity && capacity.value],
  disabled: [minimum.disabled, maximum.disabled, capacity && capacity.disabled],
  payload: UI.assessmentPayloadFromValues(enabledValues()).component_overrides
};
metric.value = '';
metric.dispatch('change');
const afterClear = {
  values: [minimum.value, maximum.value, capacity && capacity.value],
  disabled: [minimum.disabled, maximum.disabled, capacity && capacity.disabled],
  payload: UI.assessmentPayloadFromValues(enabledValues()).component_overrides
};
view.showAssessmentFormError('Could not save these facts.');
const feedback = document.getElementById('assessment-save-feedback');
const evidenceText = walk(document.getElementById('assessment-evidence-list')).map(node => node.textContent).filter(Boolean);
process.stdout.write(JSON.stringify({before, afterClear, evidenceText, feedback: {text: feedback.textContent, hidden: feedback.hidden, focused: feedback.focused}}));
""")

    assert result["before"] == {
        "metricOptions": ["", "years", "cycles", "cycles_to_capacity"],
        "values": ["cycles_to_capacity", "700", "900", "80"],
        "disabled": [False, False, False],
        "payload": {
            "battery": {
                "lifecycle": {
                    "metric": "cycles_to_capacity",
                    "minimum": 700,
                    "maximum": 900,
                    "capacity_percent": 80,
                }
            }
        },
    }
    assert result["afterClear"] == {
        "values": ["", "", ""],
        "disabled": [True, True, True],
        "payload": {},
    }
    assert result["feedback"] == {
        "text": "Could not save these facts.",
        "hidden": False,
        "focused": True,
    }
    assert "User confirmed or corrected" in result["evidenceText"]
    assert "Awaiting user confirmation" not in result["evidenceText"]


def test_dom_history_correction_without_model_score_never_fabricates_zero_percent():
    result = _run_ui_contract(FAKE_DOM + r"""
const UI = require(process.argv[1]);
const document = new FakeDocument();
const view = UI.createDomView(document);
view.renderCorrection({
  scan_id: 'scan-fourth',
  model_class_name: '0306_mobile_phone', model_confidence: .91,
  confirmed_class_name: '0401_headphones', confirmed_confidence: null,
  confirmation_source: 'user'
});
process.stdout.write(JSON.stringify({
  category: document.getElementById('result-category').textContent,
  note: document.getElementById('selection-note').textContent
}));
""")

    assert result["category"] == "Headphones"
    assert "0%" not in result["note"]
    assert "not among the model alternatives displayed" in result["note"]


def test_dom_save_then_back_to_scan_and_history_reopen_show_the_confirmed_category():
    result = _run_ui_contract(FAKE_DOM + r"""
const UI = require(process.argv[1]);
const document = new FakeDocument();
const domView = UI.createDomView(document);
const categories = [
  {category_id: '0306_mobile_phone', display_name: 'Mobile phone'},
  {category_id: '0303_laptop', display_name: 'Laptop'},
  {category_id: '0301_computer_mouse', display_name: 'Computer mouse'},
  {category_id: '0401_headphones', display_name: 'Headphones'}
];
const prediction = {
  class_name: '0306_mobile_phone', confidence: .91,
  topk: [
    {class_name: '0306_mobile_phone', confidence: .91},
    {class_name: '0303_laptop', confidence: .06},
    {class_name: '0301_computer_mouse', confidence: .03}
  ]
};
const confirmationRecord = {
  scan_id: 'scan-dom-fourth', prediction,
  confirmation: {accepted_class_name: '0401_headphones', source: 'user'}
};
const template = {
  category_id: '0306_mobile_phone', display_name: 'Mobile phone',
  template_version: '1.0.0', components: [], rules: []
};
const saved = {
  scan_id: 'scan-dom-fourth', category_id: '0401_headphones', template_version: '1.0.0',
  template: {...template, category_id: '0401_headphones', display_name: 'Headphones'},
  inputs: {usage: 'unknown', condition: 'unknown', operational: 'working', age_months: null, cycle_count: null},
  component_overrides: {}, components: []
};
const view = {
  ...domView,
  readAssessmentForm() {
    return {...saved.inputs, component_overrides: {}};
  },
  getAssessmentCategory() { return '0401_headphones'; }
};
const fetchImpl = async (url, options = {}) => {
  if (url === '/api/v1/reference/categories') return {ok: true, json: async () => categories};
  if (url === '/api/v1/scans/scan-dom-fourth/assessment' && !options.method) {
    return {ok: false, status: 409, json: async () => ({error: 'confirm category'})};
  }
  if (url === '/api/v1/reference/categories/0306_mobile_phone') {
    return {ok: true, json: async () => template};
  }
  if (url === '/api/v1/history/scan-dom-fourth/confirmation') {
    return {ok: true, json: async () => confirmationRecord};
  }
  if (url === '/api/v1/scans/scan-dom-fourth/assessment' && options.method === 'PUT') {
    return {ok: true, json: async () => saved};
  }
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({
  view, fetchImpl, formDataFactory: () => ({append() {}}),
  nextFrame: async () => {}, objectUrl: () => ''
});
function scanSnapshot() {
  return {
    scanHidden: document.getElementById('scan-view').hidden,
    category: document.getElementById('result-category').textContent,
    label: document.getElementById('category-label').textContent,
    badge: document.getElementById('result-badge').textContent,
    note: document.getElementById('selection-note').textContent,
    liveStatus: document.getElementById('live-status').textContent
  };
}
(async () => {
  controller.openHistory({scan_id: 'scan-dom-fourth', prediction});
  await controller.openAssessment();
  const savedResult = await controller.saveAssessment({});
  view.showSection('scan');
  const afterBack = scanSnapshot();
  controller.openHistory(confirmationRecord);
  await new Promise(resolve => setTimeout(resolve, 0));
  const afterHistory = scanSnapshot();
  process.stdout.write(JSON.stringify({savedResult, afterBack, afterHistory}));
})();
""")

    assert result["savedResult"] is True
    for snapshot in (result["afterBack"], result["afterHistory"]):
        assert snapshot["scanHidden"] is False
        assert snapshot["category"] == "Headphones"
        assert snapshot["label"] == "Confirmed category"
        assert snapshot["badge"] == "User correction"
        assert "0%" not in snapshot["note"]
        assert "not among the model alternatives displayed" in snapshot["note"]
    assert result["afterHistory"]["liveStatus"] == (
        "Headphones opened as a user-confirmed category."
    )


def test_assessment_presentation_keeps_ranges_units_unknowns_and_provenance_honest():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const presentation = UI.buildAssessmentPresentation({
  template_version: '1.0.0',
  template: {
    category_id: '0306_mobile_phone', display_name: 'Mobile phone',
    handling_note: 'Potential context only.',
    rules: [{text: 'Use a battery collection option.', source_ids: ['epa-battery'], reviewed_on: '2026-09-05', revision: '1.0.0'}]
  },
  inputs: {age_months: {minimum: 24, maximum: 36}, cycle_count: {minimum: 200, maximum: 400},
           known_issues: {overheating: true, odor: false, swelling_or_battery_damage: false, recall: false,
                          notes: 'Gets hot while charging.'}},
  components: [
    {
      component_id: 'battery', display_name: 'Battery', presence_label: 'standard', safety_sensitive: true,
      lifecycle: {metric: 'cycles_to_capacity', minimum: 800, maximum: 800, capacity_percent: 80,
                  source_ids: ['eu-phone']},
      source_ids: ['eu-phone'], evidence_grade: 'regulatory_minimum', reviewed_on: '2026-09-05',
      result: {percent_used: null, confidence: 'unavailable', recommendation: 'unknown',
               reasons: ['The sourced cycle endpoint is 80% capacity; it is not a total lifecycle endpoint.'],
               evidence: [{kind: 'cycle_count', detail: 'User-reported cycles: 200–400.', source_ids: []}]}
    },
    {
      component_id: 'camera', display_name: 'Camera', presence_label: 'common', lifecycle: null,
      result: {percent_used: null, confidence: 'unavailable', recommendation: 'unknown',
               reasons: ['No supported lifecycle reference is available for this component.'], evidence: []}
    },
    {
      component_id: 'display', display_name: 'Display', presence_label: 'standard', lifecycle: {metric: 'years', minimum: 4, maximum: 6,
                  source_ids: ['display-study']}, source_ids: ['display-study'], evidence_grade: 'primary_study', reviewed_on: '2026-09-05',
      result: {percent_used: {minimum: 33, maximum: 75}, confidence: 'moderate', recommendation: 'likely_reusable',
               reasons: ['Working status supports likely reuse.'], evidence: []}
    }
  ]
});
process.stdout.write(JSON.stringify(presentation));
""")

    assert result["overall_range"] == "33–75% used"
    assert result["components"][0]["range"] == "Unknown"
    assert result["components"][0]["reference_range"] == "800 cycles to 80% capacity"
    assert result["components"][0]["source_label"] == "eu-phone · regulatory minimum · reviewed 2026-09-05"
    assert result["components"][1]["range"] == "Unknown"
    assert "reviewed component lifecycle reference" in result["components"][1]["missing_guidance"]
    assert result["safety"][0]["source_label"] == (
        "epa-battery · reviewed 2026-09-05 · rule revision 1.0.0"
    )
    assert result["components"][2]["range"] == "33–75% used"
    assert result["input_evidence"] == [
        {"label": "Age", "value": "24–36 months"},
        {"label": "Cycles", "value": "200–400 cycles"},
        {"label": "Usage", "value": "Unknown"},
        {"label": "Visible condition", "value": "Unknown"},
        {"label": "Operating state", "value": "Unknown"},
        {"label": "Known issues (user reported)", "value": "Overheating"},
        {
            "label": "Issue notes (user reported)",
            "value": "Gets hot while charging.",
        },
    ]


def test_dom_rehydrates_known_issues_and_renders_hostile_notes_as_text():
    result = _run_ui_contract(FAKE_DOM + r"""
const UI = require(process.argv[1]);
const document = new FakeDocument();
const view = UI.createDomView(document);
const note = '<img src=x onerror=alert(1)> battery smells odd';
const assessment = {
  scan_id: 'issue-scan', category_id: '0306_mobile_phone', template_version: '2.0.0',
  template: {category_id: '0306_mobile_phone', display_name: 'Mobile phone', template_version: '2.0.0',
             components: [], rules: []},
  inputs: {age_months: null, cycle_count: null, usage: 'unknown', condition: 'unknown', operational: 'working',
           known_issues: {overheating: false, odor: true, swelling_or_battery_damage: false, recall: false, notes: note}},
  component_overrides: {}, components: []
};
view.renderAssessment({assessment, categories: [{category_id: '0306_mobile_phone', display_name: 'Mobile phone'}], context: {}});
const evidence = walk(document.getElementById('assessment-evidence-list')).map(node => node.textContent).filter(Boolean);
process.stdout.write(JSON.stringify({
  odor: document.getElementById('assessment-issue-odor').checked,
  overheating: document.getElementById('assessment-issue-overheating').checked,
  note: document.getElementById('assessment-issue-notes').value,
  evidence
}));
""")

    assert result["odor"] is True
    assert result["overheating"] is False
    assert result["note"] == "<img src=x onerror=alert(1)> battery smells odd"
    assert any(result["note"] in text for text in result["evidence"])


def test_dom_safety_escalation_is_an_accessible_alert_before_components():
    result = _run_ui_contract(FAKE_DOM + r"""
const UI = require(process.argv[1]);
const document = new FakeDocument();
const view = UI.createDomView(document);
const component = {
  component_id: 'battery', display_name: 'Battery', presence_label: 'standard',
  safety_sensitive: true, lifecycle: null, source_ids: ['battery-source'],
  evidence_grade: 'guidance', reviewed_on: '2026-09-05',
  result: {percent_used: null, confidence: 'unavailable', recommendation: 'specialist_handling',
           reasons: ['User-reported overheating needs specialist handling.'], evidence: []}
};
const assessment = {
  category_id: '0306_mobile_phone', template_version: '2.0.0',
  template: {category_id: '0306_mobile_phone', display_name: 'Mobile phone', template_version: '2.0.0',
             components: [component], rules: []},
  inputs: {}, component_overrides: {}, components: [component]
};
view.renderAssessment({assessment, categories: [{category_id: '0306_mobile_phone', display_name: 'Mobile phone'}], context: {}});
const alerts = walk(document.getElementById('assessment-safety-list')).filter(node => node.attributes.role === 'alert');
process.stdout.write(JSON.stringify({count: alerts.length, label: alerts[0] && alerts[0].attributes['aria-label'], text: alerts[0] && walk(alerts[0]).map(node => node.textContent).join(' ')}));
""")

    assert result["count"] == 1
    assert result["label"] == "Safety escalation"
    assert "overheating" in result["text"].lower()


def test_safety_escalation_keeps_immutable_provenance_separate_from_override():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const presentation = UI.buildAssessmentPresentation({
  category_id: '0306_mobile_phone', template_version: '1.0.0',
  template: {category_id: '0306_mobile_phone', display_name: 'Mobile phone', rules: []},
  inputs: {},
  components: [{
    component_id: 'battery', display_name: 'Battery', presence_label: 'standard', safety_sensitive: true,
    source_ids: ['immutable-battery-safety'], evidence_grade: 'regulatory', reviewed_on: '2026-09-05',
    lifecycle: {metric: 'years', minimum: 2, maximum: 3, source_ids: [], evidence_grade: 'user_provided_unverified', reviewed_on: null},
    result: {percent_used: null, confidence: 'unavailable', recommendation: 'specialist_handling',
             reasons: ['Stop handling and use a specialist.'], evidence: []}
  }]
});
const withoutLifecycle = UI.buildAssessmentPresentation({
  category_id: '0401_headphones', template_version: '1.0.0',
  template: {category_id: '0401_headphones', display_name: 'Headphones', rules: []},
  inputs: {},
  components: [{
    component_id: 'battery', display_name: 'Battery', presence_label: 'optional', safety_sensitive: true,
    source_ids: ['immutable-battery-safety'], evidence_grade: 'regulatory', reviewed_on: '2026-09-05',
    lifecycle: null,
    result: {percent_used: null, confidence: 'unavailable', recommendation: 'unknown', reasons: [], evidence: []}
  }]
});
process.stdout.write(JSON.stringify({presentation, withoutLifecycle}));
""")

    component = result["presentation"]["components"][0]
    assert component["lifecycle_source_label"] == "user provided unverified"
    assert component["safety_source_label"] == (
        "immutable-battery-safety · regulatory · reviewed 2026-09-05"
    )
    assert result["presentation"]["safety"][0]["source_label"] == component["safety_source_label"]
    no_lifecycle = result["withoutLifecycle"]["components"][0]
    assert no_lifecycle["lifecycle_source_label"] == "No reviewed source attached"
    assert no_lifecycle["safety_source_label"] == component["safety_source_label"]


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


def test_save_validation_and_api_errors_preserve_the_editable_form_for_retry():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const states = [], busy = [], errors = [], clears = [], requests = [], renders = [];
const form = {marker: 'same-form', note: 'unsaved headphones facts'};
let phase = 'parse-error';
let confirmationAttempts = 0;
const categories = [
  {category_id: '0306_mobile_phone', display_name: 'Mobile phone'},
  {category_id: '0401_headphones', display_name: 'Headphones'}
];
const template = {category_id: '0306_mobile_phone', display_name: 'Mobile phone', template_version: '1.0.0', components: [], rules: []};
const saved = {scan_id: 'scan-errors', category_id: '0401_headphones', template_version: '1.0.0', template: {...template, category_id: '0401_headphones', display_name: 'Headphones'},
               inputs: {usage: 'heavy', condition: 'visible_wear', operational: 'working', age_months: null, cycle_count: null},
               component_overrides: {}, components: []};
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {}, renderHistory() {}, markHistoryDeleting() {},
  showSection() {}, clearPreview() {},
  setAssessmentState(state, message) { states.push([state, message || null]); },
  setAssessmentBusy(value) { busy.push(value); },
  showAssessmentFormError(message) { errors.push(message); },
  clearAssessmentFormError() { clears.push(true); },
  renderAssessmentDraft() {},
  renderAssessment(value) { renders.push(value); },
  readAssessmentForm(receivedForm) {
    if (receivedForm !== form) throw new Error('form identity was lost');
    if (phase === 'parse-error') throw new Error('Age must be a non-negative range with the lower value first.');
    return {age_months: null, cycle_count: null, usage: 'heavy', condition: 'visible_wear', operational: 'working', component_overrides: {}};
  },
  getAssessmentCategory(receivedForm) {
    if (receivedForm !== form) throw new Error('form identity was lost');
    return '0401_headphones';
  }
};
const fetchImpl = async (url, options = {}) => {
  requests.push([url, options.method || 'GET']);
  if (url === '/api/v1/reference/categories') return {ok: true, json: async () => categories};
  if (url === '/api/v1/scans/scan-errors/assessment' && !options.method) return {ok: false, status: 409, json: async () => ({error: 'confirm category'})};
  if (url === '/api/v1/reference/categories/0306_mobile_phone') return {ok: true, json: async () => template};
  if (url === '/api/v1/history/scan-errors/confirmation') {
    confirmationAttempts += 1;
    if (confirmationAttempts === 1) return {ok: false, status: 503, json: async () => ({error: 'disk is temporarily unavailable'})};
    return {ok: true, json: async () => ({
      prediction: {class_name: '0306_mobile_phone', confidence: .91, topk: [{class_name: '0306_mobile_phone', confidence: .91}]},
      confirmation: {accepted_class_name: '0401_headphones', source: 'user'}
    })};
  }
  if (url === '/api/v1/scans/scan-errors/assessment' && options.method === 'PUT') return {ok: true, json: async () => saved};
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => ''});
(async () => {
  controller.openHistory({scan_id: 'scan-errors', prediction: {class_name: '0306_mobile_phone', confidence: .91, topk: [{class_name: '0306_mobile_phone', confidence: .91}]}});
  await controller.openAssessment();
  states.length = 0; busy.length = 0; requests.length = 0; errors.length = 0; clears.length = 0; renders.length = 0;

  const parseSaved = await controller.saveAssessment(form);
  const afterParse = {states: [...states], busy: [...busy], requests: [...requests], errors: [...errors], renders: renders.length};

  phase = 'api-error'; states.length = 0; busy.length = 0; requests.length = 0; errors.length = 0; clears.length = 0;
  const apiSaved = await controller.saveAssessment(form);
  const afterApi = {states: [...states], busy: [...busy], requests: [...requests], errors: [...errors], renders: renders.length, note: form.note};

  phase = 'success'; states.length = 0; busy.length = 0; requests.length = 0; errors.length = 0; clears.length = 0;
  const retrySaved = await controller.saveAssessment(form);
  const afterRetry = {states: [...states], busy: [...busy], requests: [...requests], errors: [...errors], renders: renders.length, note: form.note};
  process.stdout.write(JSON.stringify({parseSaved, apiSaved, retrySaved, afterParse, afterApi, afterRetry}));
})();
""")

    assert result["parseSaved"] is False
    assert result["afterParse"] == {
        "states": [["assessment-editing", None]],
        "busy": [],
        "requests": [],
        "errors": ["Age must be a non-negative range with the lower value first."],
        "renders": 0,
    }
    assert result["apiSaved"] is False
    assert result["afterApi"] == {
        "states": [
            ["assessment-loading", None],
            ["assessment-editing", None],
        ],
        "busy": [True, False],
        "requests": [["/api/v1/history/scan-errors/confirmation", "PUT"]],
        "errors": ["disk is temporarily unavailable"],
        "renders": 0,
        "note": "unsaved headphones facts",
    }
    assert result["retrySaved"] is True
    assert result["afterRetry"]["states"] == [
        ["assessment-loading", None],
        ["assessment-ready", "Headphones assessment updated."],
    ]
    assert result["afterRetry"]["busy"] == [True, False]
    assert result["afterRetry"]["requests"] == [
        ["/api/v1/history/scan-errors/confirmation", "PUT"],
        ["/api/v1/scans/scan-errors/assessment", "PUT"],
    ]
    assert result["afterRetry"]["renders"] == 1
    assert result["afterRetry"]["note"] == "unsaved headphones facts"


def test_reopening_same_assessment_does_not_leak_or_steal_save_ownership():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const busy = [], requests = [];
let assessmentGets = 0;
let confirmationCount = 0;
let resolveFirst;
const categories = [{category_id: '0306_mobile_phone', display_name: 'Mobile phone'}];
const template = {category_id: '0306_mobile_phone', display_name: 'Mobile phone', template_version: '1.0.0', components: [], rules: []};
const saved = {scan_id: 'race-scan', category_id: '0306_mobile_phone', template_version: '1.0.0', template,
               inputs: {usage: 'unknown', condition: 'unknown', operational: 'working', age_months: null, cycle_count: null}, component_overrides: {}, components: []};
const confirmationRecord = {prediction: {class_name: '0306_mobile_phone', confidence: .91, topk: [{class_name: '0306_mobile_phone', confidence: .91}]},
                            confirmation: {accepted_class_name: '0306_mobile_phone', source: 'user'}};
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {}, renderHistory() {}, markHistoryDeleting() {},
  showSection() {}, clearPreview() {}, setAssessmentState() {},
  setAssessmentBusy(value) { busy.push(value); },
  clearAssessmentFormError() {}, showAssessmentFormError() {}, renderAssessmentDraft() {}, renderAssessment() {},
  readAssessmentForm() { return {age_months: null, cycle_count: null, usage: 'unknown', condition: 'unknown', operational: 'working', component_overrides: {}}; },
  getAssessmentCategory() { return '0306_mobile_phone'; }
};
const fetchImpl = (url, options = {}) => {
  requests.push([url, options.method || 'GET']);
  if (url === '/api/v1/reference/categories') return Promise.resolve({ok: true, json: async () => categories});
  if (url === '/api/v1/scans/race-scan/assessment' && !options.method) {
    assessmentGets += 1;
    if (assessmentGets === 1) return Promise.resolve({ok: false, status: 409, json: async () => ({error: 'confirm category'})});
    return Promise.resolve({ok: true, json: async () => saved});
  }
  if (url === '/api/v1/reference/categories/0306_mobile_phone') return Promise.resolve({ok: true, json: async () => template});
  if (url === '/api/v1/history/race-scan/confirmation') {
    confirmationCount += 1;
    if (confirmationCount === 1) return new Promise(resolve => { resolveFirst = () => resolve({ok: true, json: async () => confirmationRecord}); });
    return Promise.resolve({ok: true, json: async () => confirmationRecord});
  }
  if (url === '/api/v1/scans/race-scan/assessment' && options.method === 'PUT') return Promise.resolve({ok: true, json: async () => saved});
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => ''});
(async () => {
  controller.openHistory({scan_id: 'race-scan', prediction: confirmationRecord.prediction});
  await controller.openAssessment();
  const first = controller.saveAssessment({});
  await new Promise(resolve => setImmediate(resolve));
  const reopened = await controller.openAssessment();
  const second = controller.saveAssessment({});
  await new Promise(resolve => setImmediate(resolve));
  const blockedBeforeStale = await controller.saveAssessment({});

  if (resolveFirst) resolveFirst();
  const firstSaved = await first;
  const blockedAfterStale = await controller.saveAssessment({});

  const secondSaved = await second;
  const laterSaved = await controller.saveAssessment({});
  process.stdout.write(JSON.stringify({reopened, firstSaved, secondSaved, blockedBeforeStale, blockedAfterStale, laterSaved, confirmationCount, busy, requests}));
})();
""")

    assert result["reopened"] is True
    assert result["firstSaved"] is False
    assert result["secondSaved"] is True
    assert result["blockedBeforeStale"] is False
    assert result["blockedAfterStale"] is False
    assert result["laterSaved"] is True
    assert result["confirmationCount"] == 2
    # Reopening cancels the first token, then each later owner releases only itself.
    assert result["busy"] == [True, False, True, False, True, False]


def test_fourth_reference_category_confirmation_updates_evidence_and_survives_reopen():
    result = _run_ui_contract(r"""
const UI = require(process.argv[1]);
const renderedContexts = [], scanCorrections = [], requests = [];
let assessmentGets = 0;
const categories = [
  {category_id: '0306_mobile_phone', display_name: 'Mobile phone'},
  {category_id: '0303_laptop', display_name: 'Laptop'},
  {category_id: '0301_computer_mouse', display_name: 'Computer mouse'},
  {category_id: '0401_headphones', display_name: 'Headphones'}
];
const phoneTemplate = {category_id: '0306_mobile_phone', display_name: 'Mobile phone', template_version: '1.0.0', components: [], rules: []};
const headphonesTemplate = {category_id: '0401_headphones', display_name: 'Headphones', template_version: '1.0.0', components: [], rules: []};
const prediction = {
  class_name: '0306_mobile_phone', confidence: .91,
  topk: [
    {class_name: '0306_mobile_phone', confidence: .91},
    {class_name: '0303_laptop', confidence: .06},
    {class_name: '0301_computer_mouse', confidence: .03}
  ]
};
const confirmationRecord = {
  scan_id: 'scan-fourth', prediction,
  confirmation: {accepted_class_name: '0401_headphones', source: 'user'}
};
const saved = {scan_id: 'scan-fourth', category_id: '0401_headphones', template_version: '1.0.0', template: headphonesTemplate,
               inputs: {usage: 'unknown', condition: 'unknown', operational: 'unknown', age_months: null, cycle_count: null}, component_overrides: {}, components: []};
const view = {
  transition() {}, setBusy() {}, showPreview() {}, renderInfluence() {}, renderHistory() {}, markHistoryDeleting() {},
  showSection() {}, clearPreview() {}, setAssessmentState() {}, setAssessmentBusy() {},
  clearAssessmentFormError() {}, showAssessmentFormError() {}, renderAssessmentDraft() {},
  renderAssessment(value) { renderedContexts.push(JSON.parse(JSON.stringify(value.context))); },
  renderCorrection(value, shouldAnnounce) {
    scanCorrections.push({
      confirmed_class_name: value.confirmed_class_name,
      confirmed_confidence: value.confirmed_confidence,
      confirmation_source: value.confirmation_source,
      shouldAnnounce
    });
  },
  readAssessmentForm() { return saved.inputs; },
  getAssessmentCategory() { return '0401_headphones'; }
};
const fetchImpl = async (url, options = {}) => {
  requests.push([url, options.method || 'GET']);
  if (url === '/api/v1/reference/categories') return {ok: true, json: async () => categories};
  if (url === '/api/v1/scans/scan-fourth/assessment' && !options.method) {
    assessmentGets += 1;
    if (assessmentGets === 1) return {ok: false, status: 409, json: async () => ({error: 'confirm category'})};
    return {ok: true, json: async () => saved};
  }
  if (url === '/api/v1/reference/categories/0306_mobile_phone') return {ok: true, json: async () => phoneTemplate};
  if (url === '/api/v1/history/scan-fourth/confirmation') return {ok: true, json: async () => confirmationRecord};
  if (url === '/api/v1/scans/scan-fourth/assessment' && options.method === 'PUT') return {ok: true, json: async () => saved};
  throw new Error('unexpected request ' + url);
};
const controller = UI.createController({view, fetchImpl, formDataFactory: () => ({append() {}}), nextFrame: async () => {}, objectUrl: () => ''});
(async () => {
  controller.openHistory({scan_id: 'scan-fourth', prediction});
  await controller.openAssessment();
  const savedResult = await controller.saveAssessment({});
  const immediate = controller.getAssessmentContext();
  const reopened = await controller.openAssessment();
  const afterReopen = controller.getAssessmentContext();
  process.stdout.write(JSON.stringify({savedResult, reopened, immediate, afterReopen, renderedContexts, scanCorrections, requests}));
})();
""")

    expected_context = {
        "scan_id": "scan-fourth",
        "confirmed_class_name": "0401_headphones",
        "model_evidence": {
            "class_name": "0306_mobile_phone",
            "confidence": 0.91,
        },
        "confirmation": {
            "source": "user",
            "selected_model_score": None,
        },
    }
    assert result["savedResult"] is True
    assert result["reopened"] is True
    assert result["immediate"] == expected_context
    assert result["afterReopen"] == expected_context
    assert result["renderedContexts"] == [expected_context, expected_context]
    assert result["scanCorrections"] == [{
        "confirmed_class_name": "0401_headphones",
        "confirmed_confidence": None,
        "confirmation_source": "user",
        "shouldAnnounce": False,
    }]
    assert ["/api/v1/history/scan-fourth/confirmation", "PUT"] in result["requests"]


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
