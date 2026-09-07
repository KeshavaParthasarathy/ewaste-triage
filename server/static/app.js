(function (global) {
  "use strict";

  const SUPPORTED_MIME = new Set([
    "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"
  ]);
  const SUPPORTED_EXTENSION = /\.(?:jpe?g|png|webp|heic|heif)$/i;
  const LABELS = {
    "0301_computer_mouse": "Computer mouse",
    "0301_keyboard": "Keyboard",
    "0301_small_it": "Small IT device",
    "0303_laptop": "Laptop",
    "0306_mobile_phone": "Mobile phone",
    "0306_mobile_phones": "Mobile phone",
    "0401_headphones": "Headphones"
  };
  const RECOMMENDATION_LABELS = {
    likely_reusable: "Likely reusable after test",
    diagnostic_test: "Run a diagnostic test",
    repair_assessment: "Arrange a repair assessment",
    recycle: "Route to appropriate recycling",
    specialist_handling: "Use specialist handling",
    unknown: "More evidence needed"
  };
  const KNOWN_ISSUE_LABELS = {
    overheating: "Overheating",
    odor: "Unusual odor",
    swelling_or_battery_damage: "Swelling or battery damage",
    recall: "Known recall"
  };
  const MAX_KNOWN_ISSUE_NOTES_CODE_POINTS = 500;
  const CLEAR_HISTORY_CONFIRMATION =
    "Delete every locally saved scan? You will have a brief chance to undo before deletion completes.";

  function confirmClearHistory(confirmImpl) {
    return Boolean(confirmImpl(CLEAR_HISTORY_CONFIRMATION));
  }

  function isSupportedImage(file) {
    if (!file || !file.name) return false;
    return SUPPORTED_MIME.has(String(file.type || "").toLowerCase()) ||
      SUPPORTED_EXTENSION.test(file.name);
  }

  function formatCategory(className) {
    if (!className) return "Unknown category";
    if (LABELS[className]) return LABELS[className];
    const plain = String(className).replace(/^\d{4}_/, "").replace(/_/g, " ");
    return plain.charAt(0).toUpperCase() + plain.slice(1);
  }

  function percent(value) {
    const bounded = Math.max(0, Math.min(1, Number(value) || 0));
    return `${Math.round(bounded * 100)}%`;
  }

  function currency(value) {
    return new Intl.NumberFormat(undefined, {
      style: "currency", currency: "USD", maximumFractionDigits: 2
    }).format(Number(value) || 0);
  }

  async function responseJson(response) {
    let payload = {};
    try {
      payload = await response.json();
    } catch (_error) {
      payload = {};
    }
    if (!response.ok) {
      const error = new Error(payload.error || `Request failed (${response.status || "offline"})`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function rangeFromValues(minimumValue, maximumValue, label) {
    const minimumBlank = minimumValue === undefined || minimumValue === null || minimumValue === "";
    const maximumBlank = maximumValue === undefined || maximumValue === null || maximumValue === "";
    if (minimumBlank && maximumBlank) return null;
    const minimum = Number(minimumBlank ? maximumValue : minimumValue);
    const maximum = Number(maximumBlank ? minimumValue : maximumValue);
    if (!Number.isInteger(minimum) || !Number.isInteger(maximum) || minimum < 0 || maximum < minimum) {
      throw new Error(`${label} must be a non-negative range with the lower value first.`);
    }
    return {minimum, maximum};
  }

  function assessmentPayloadFromValues(values) {
    const issueChecked = value => value === true || value === "true" ||
      value === "on" || value === "1";
    const issueNotes = values.issue_notes === undefined || values.issue_notes === null ?
      "" : String(values.issue_notes).trim();
    if (Array.from(issueNotes).length > MAX_KNOWN_ISSUE_NOTES_CODE_POINTS) {
      throw new Error(
        `Known-issue notes must be ${MAX_KNOWN_ISSUE_NOTES_CODE_POINTS} characters or fewer.`
      );
    }
    const payload = {
      age_months: rangeFromValues(values.age_min, values.age_max, "Age"),
      cycle_count: rangeFromValues(values.cycle_min, values.cycle_max, "Cycle count"),
      usage: values.usage || "unknown",
      condition: values.condition || "unknown",
      operational: values.operational || "unknown",
      known_issues: {
        overheating: issueChecked(values.issue_overheating),
        odor: issueChecked(values.issue_odor),
        swelling_or_battery_damage: issueChecked(values.issue_swelling_or_battery_damage),
        recall: issueChecked(values.issue_recall),
        notes: issueNotes || null
      },
      component_overrides: {}
    };
    const componentFields = {};
    for (const [name, rawValue] of Object.entries(values)) {
      const match = /^component\.([^.]+)\.(presence|condition|lifecycle_metric|lifecycle_min|lifecycle_max|lifecycle_capacity)$/.exec(name);
      if (!match || rawValue === undefined || rawValue === null) continue;
      if (rawValue === "" && match[2] !== "lifecycle_metric") continue;
      if (!componentFields[match[1]]) componentFields[match[1]] = {};
      componentFields[match[1]][match[2]] = rawValue;
    }
    for (const [componentId, fields] of Object.entries(componentFields)) {
      const override = {};
      if (fields.presence) override.presence_label = fields.presence;
      if (fields.condition) override.condition = fields.condition;
      if (fields.lifecycle_metric) {
        if (!["years", "cycles", "cycles_to_capacity"].includes(fields.lifecycle_metric)) {
          throw new Error("Choose years, cycles, or cycles to capacity for the component lifecycle reference.");
        }
        const range = rangeFromValues(fields.lifecycle_min, fields.lifecycle_max, "Component lifecycle");
        if (range === null) throw new Error("Enter a component lifecycle range.");
        override.lifecycle = {metric: fields.lifecycle_metric, ...range};
        if (fields.lifecycle_metric === "cycles_to_capacity") {
          if (fields.lifecycle_capacity === undefined || fields.lifecycle_capacity === "") {
            throw new Error("Enter the capacity percentage for cycles to capacity.");
          }
          const capacity = Number(fields.lifecycle_capacity);
          if (!Number.isInteger(capacity) || capacity < 1 || capacity > 100) {
            throw new Error("Capacity percentage must be an integer from 1 to 100.");
          }
          override.lifecycle.capacity_percent = capacity;
        }
      }
      if (Object.keys(override).length) payload.component_overrides[componentId] = override;
    }
    return payload;
  }

  function validateKnownIssueNotesControl(control) {
    const value = String((control && control.value) || "").trim();
    const valid = Array.from(value).length <= MAX_KNOWN_ISSUE_NOTES_CODE_POINTS;
    const message = valid ? "" :
      `Known-issue notes must be ${MAX_KNOWN_ISSUE_NOTES_CODE_POINTS} characters or fewer.`;
    if (control && typeof control.setCustomValidity === "function") {
      control.setCustomValidity(message);
    }
    if (control && valid && typeof control.removeAttribute === "function") {
      control.removeAttribute("aria-invalid");
    } else if (control && !valid && typeof control.setAttribute === "function") {
      control.setAttribute("aria-invalid", "true");
    }
    return valid;
  }

  function rangeWithUnit(value, unit) {
    if (!value) return "Unknown";
    const range = value.minimum === value.maximum ? `${value.minimum}` : `${value.minimum}–${value.maximum}`;
    return `${range}${unit.startsWith("%") ? "" : " "}${unit}`;
  }

  function sourceLabel(sourceIds, grade, reviewedOn, revision) {
    const parts = [];
    if (Array.isArray(sourceIds) && sourceIds.length) parts.push(sourceIds.join(", "));
    if (grade) parts.push(String(grade).replace(/_/g, " "));
    if (reviewedOn) parts.push(`reviewed ${reviewedOn}`);
    if (revision) parts.push(`rule revision ${revision}`);
    return parts.join(" · ") || "No reviewed source attached";
  }

  function readableValue(value) {
    if (!value || value === "unknown") return "Unknown";
    const text = String(value).replace(/_/g, " ");
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function lifecycleReferenceLabel(lifecycle) {
    if (!lifecycle) return "No sourced lifecycle range";
    const numeric = lifecycle.minimum === lifecycle.maximum ?
      `${lifecycle.minimum}` : `${lifecycle.minimum}–${lifecycle.maximum}`;
    if (lifecycle.metric === "years") return `${numeric} years`;
    if (lifecycle.metric === "cycles_to_capacity") {
      return `${numeric} cycles to ${lifecycle.capacity_percent}% capacity`;
    }
    return `${numeric} cycles`;
  }

  function buildAssessmentPresentation(assessment) {
    const template = assessment.template || {};
    const inputs = assessment.inputs || {};
    const components = (Array.isArray(assessment.components) ? assessment.components : []).map(component => {
      const result = component.result || {};
      const lifecycle = component.lifecycle || null;
      const lifecycleOwnsSources = lifecycle && Object.prototype.hasOwnProperty.call(lifecycle, "source_ids");
      const lifecycleOwnsGrade = lifecycle && Object.prototype.hasOwnProperty.call(lifecycle, "evidence_grade");
      const lifecycleOwnsReview = lifecycle && Object.prototype.hasOwnProperty.call(lifecycle, "reviewed_on");
      const lifecycleSources = !lifecycle ? [] :
        lifecycleOwnsSources ? lifecycle.source_ids : component.source_ids;
      const lifecycleGrade = !lifecycle ? null :
        lifecycleOwnsGrade ? lifecycle.evidence_grade : component.evidence_grade;
      const lifecycleReview = !lifecycle ? null :
        lifecycleOwnsReview ? lifecycle.reviewed_on : component.reviewed_on;
      const hasReviewedReference = lifecycle && Array.isArray(lifecycleSources) && lifecycleSources.length;
      const lifecycleSourceLabel = sourceLabel(
        lifecycleSources,
        lifecycleGrade,
        lifecycleReview
      );
      const safetySourceLabel = sourceLabel(
        component.source_ids,
        component.evidence_grade,
        component.reviewed_on
      );
      let missingGuidance = "";
      if (!result.percent_used && !hasReviewedReference) {
        missingGuidance = "Needs a reviewed component lifecycle reference or supported diagnostic; age or usage alone cannot improve this value.";
      } else if (!result.percent_used) {
        missingGuidance = (result.reasons || []).join(" ") || "Add the missing item input named by the lifecycle reference.";
      }
      return {
        ...component,
        range: rangeWithUnit(result.percent_used, "% used"),
        reference_range: lifecycleReferenceLabel(lifecycle),
        confidence_label: result.confidence === "unavailable" ? "Unavailable" :
          `${String(result.confidence || "unknown").replace(/_/g, " ")} confidence`,
        recommendation_label: RECOMMENDATION_LABELS[result.recommendation] || "More evidence needed",
        reasons: Array.isArray(result.reasons) ? result.reasons : [],
        evidence: Array.isArray(result.evidence) ? result.evidence : [],
        missing_guidance: missingGuidance,
        source_label: lifecycleSourceLabel,
        lifecycle_source_label: lifecycleSourceLabel,
        safety_source_label: safetySourceLabel
      };
    });
    const supportedRanges = components
      .map(component => component.result && component.result.percent_used)
      .filter(Boolean);
    const overall = supportedRanges.length ? {
      minimum: Math.min(...supportedRanges.map(value => value.minimum)),
      maximum: Math.max(...supportedRanges.map(value => value.maximum))
    } : null;
    const safety = (Array.isArray(template.rules) ? template.rules : []).map(rule => ({
      text: rule.text,
      source_label: sourceLabel(
        rule.source_ids, rule.evidence_grade, rule.reviewed_on, rule.revision
      ),
      priority: "rule"
    }));
    for (const component of components) {
      if (component.safety_sensitive && component.result && component.result.recommendation === "specialist_handling") {
        safety.unshift({
          text: `${component.display_name}: ${component.reasons.join(" ")}`,
          source_label: component.safety_source_label,
          priority: "escalation"
        });
      }
    }
    if (!safety.length && template.handling_note) {
      safety.push({
        text: template.handling_note,
        source_label: sourceLabel(template.source_ids, null, null),
        priority: "context"
      });
    }
    const knownIssues = inputs.known_issues || {};
    const knownIssueLabels = Object.entries(KNOWN_ISSUE_LABELS)
      .filter(([name]) => knownIssues[name] === true)
      .map(([, label]) => label);
    const inputEvidence = [
      {label: "Age", value: rangeWithUnit(inputs.age_months, "months")},
      {label: "Cycles", value: rangeWithUnit(inputs.cycle_count, "cycles")},
      {label: "Usage", value: readableValue(inputs.usage)},
      {label: "Visible condition", value: readableValue(inputs.condition)},
      {label: "Operating state", value: readableValue(inputs.operational)},
      {
        label: "Known issues (user reported)",
        value: knownIssueLabels.length ? knownIssueLabels.join(", ") : "None reported"
      }
    ];
    if (knownIssues.notes) {
      inputEvidence.push({
        label: "Issue notes (user reported)", value: String(knownIssues.notes)
      });
    }
    return {
      overall_range: rangeWithUnit(overall, "% used"),
      overall_maximum: overall ? overall.maximum : 0,
      overall_detail: supportedRanges.length ?
        `${supportedRanges.length} component ${supportedRanges.length === 1 ? "range is" : "ranges are"} supported by the current facts.` :
        "No component range is supported yet. Review the missing-input guidance below.",
      safety,
      components,
      input_evidence: inputEvidence,
      template_version: assessment.template_version || template.template_version || "Unknown",
      category_name: template.display_name || formatCategory(assessment.category_id),
      handling_note: template.handling_note || ""
    };
  }

  function historyPresentation(record) {
    const prediction = record && record.prediction ? record.prediction : {};
    const confirmation = record && record.confirmation ? record.confirmation : {};
    const confirmedCategory = confirmation.accepted_class_name || prediction.class_name;
    return {
      category: formatCategory(confirmedCategory),
      model_evidence: `Original model: ${formatCategory(prediction.class_name)} · ${percent(prediction.confidence)} confidence`
    };
  }

  function createController(options) {
    const view = options.view;
    const fetchImpl = options.fetchImpl;
    const formDataFactory = options.formDataFactory;
    const nextFrame = options.nextFrame;
    const objectUrl = options.objectUrl;
    const undoDelay = options.undoDelay === undefined ? 5000 : options.undoDelay;
    const phonePollDelay = options.phonePollDelay === undefined ? 1000 : options.phonePollDelay;
    const schedule = options.schedule || global.setTimeout.bind(global);
    const cancelSchedule = options.cancelSchedule || global.clearTimeout.bind(global);
    let generation = 0;
    let activeAnalysisGeneration = null;
    let activeScanId = null;
    let activeResult = null;
    let historyGeneration = 0;
    let pendingHistoryAction = null;
    let assessmentGeneration = 0;
    let assessmentSaveToken = null;
    let activeAssessment = null;
    let phoneGeneration = 0;
    let phonePollTimer = null;
    let phoneActive = false;
    let phoneStartRequest = null;
    const confirmationWriters = new Map();

    function cancelAssessmentSave() {
      if (assessmentSaveToken === null) return;
      assessmentSaveToken = null;
      if (typeof view.setAssessmentBusy === "function") view.setAssessmentBusy(false);
    }

    function withModelEvidence(result) {
      const modelClassName = result.model_class_name || result.class_name;
      const modelConfidence = result.model_confidence === undefined ?
        result.confidence : result.model_confidence;
      return {
        ...result,
        model_class_name: modelClassName,
        model_confidence: modelConfidence,
        confirmed_class_name: result.confirmed_class_name || modelClassName,
        confirmed_confidence: result.confirmed_confidence === undefined ?
          modelConfidence : result.confirmed_confidence,
        confirmation_source: result.confirmation_source || "model"
      };
    }

    function selectedModelScore(result, categoryId) {
      if (!categoryId) return null;
      const selected = (Array.isArray(result.topk) ? result.topk : []).find(
        item => item.class_name === categoryId
      );
      if (selected && selected.confidence !== undefined) return selected.confidence;
      if (categoryId === result.model_class_name) return result.model_confidence;
      return null;
    }

    function confirmationResult(record, requestedCategoryId, baseResult = activeResult) {
      const prediction = record && record.prediction ? record.prediction : {};
      const confirmation = record && record.confirmation ? record.confirmation : {};
      const current = baseResult || {};
      const modelClassName = prediction.class_name || current.model_class_name || current.class_name;
      const modelConfidence = prediction.confidence === undefined ?
        current.model_confidence : prediction.confidence;
      const merged = {
        ...current,
        ...prediction,
        scan_id: (record && record.scan_id) || current.scan_id || null,
        model_class_name: modelClassName,
        model_confidence: modelConfidence,
        confirmed_class_name: confirmation.accepted_class_name || requestedCategoryId || current.confirmed_class_name,
        confirmation_source: confirmation.source || "user"
      };
      merged.confirmed_confidence = selectedModelScore(
        merged,
        merged.confirmed_class_name
      );
      return withModelEvidence(merged);
    }

    async function api(url, init) {
      return responseJson(await fetchImpl(url, init));
    }

    function confirmationWriter(scanId) {
      if (!confirmationWriters.has(scanId)) {
        confirmationWriters.set(scanId, {
          scanId,
          inFlight: null,
          inFlightPromise: null,
          pending: null,
          latestCategory: null,
          committedResult: null,
          idleWaiters: []
        });
      }
      return confirmationWriters.get(scanId);
    }

    function seedConfirmationWriter(scanId, result) {
      const writer = confirmationWriter(scanId);
      if (!writer.committedResult && result) {
        writer.committedResult = {...result};
      }
      return writer;
    }

    function renderCommittedConfirmation(result) {
      if (!result) return;
      if (
        result.confirmation_source === "user" &&
        typeof view.renderCorrection === "function"
      ) {
        view.renderCorrection(result, false);
      } else if (typeof view.transition === "function") {
        view.transition(result.low_confidence ? "review" : "result", result);
      }
    }

    function drainConfirmationWriter(writer) {
      if (writer.inFlight || !writer.pending) return;
      const entry = writer.pending;
      writer.pending = null;
      writer.inFlight = entry;
      writer.inFlightPromise = api(`/api/v1/history/${encodeURIComponent(writer.scanId)}/confirmation`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({accepted_class_name: entry.categoryId})
      }).then(record => {
        writer.committedResult = confirmationResult(
          record,
          entry.categoryId,
          writer.committedResult
        );
        const isLatestWrite =
          !writer.pending &&
          writer.latestCategory === entry.categoryId;
        if (
          isLatestWrite &&
          activeResult &&
          activeResult.scan_id === writer.scanId
        ) {
          activeResult = {...writer.committedResult};
          renderCommittedConfirmation(activeResult);
        }
        entry.waiters.forEach(waiter => waiter.resolve(isLatestWrite ? record : false));
      }).catch(error => {
        const isLatestWrite =
          !writer.pending &&
          writer.latestCategory === entry.categoryId;
        entry.waiters.forEach(waiter => {
          if (isLatestWrite) waiter.reject(error);
          else waiter.resolve(false);
        });
        if (
          isLatestWrite &&
          entry.renderIntent &&
          activeResult &&
          activeResult.scan_id === writer.scanId &&
          writer.committedResult
        ) {
          activeResult = {...writer.committedResult};
          renderCommittedConfirmation(activeResult);
        }
        if (
          isLatestWrite &&
          entry.renderIntent &&
          activeResult &&
          activeResult.scan_id === writer.scanId &&
          typeof view.renderHistoryError === "function"
        ) {
          view.renderHistoryError(`The category change was not saved: ${error.message}`);
        }
      }).finally(() => {
        writer.inFlight = null;
        writer.inFlightPromise = null;
        drainConfirmationWriter(writer);
        if (!writer.inFlight && !writer.pending) {
          writer.idleWaiters.splice(0).forEach(resolve => resolve());
        }
      });
    }

    function persistConfirmation(scanId, categoryId, renderIntent = false) {
      const writer = seedConfirmationWriter(
        scanId,
        activeResult && activeResult.scan_id === scanId ? activeResult : null
      );
      writer.latestCategory = categoryId;
      return new Promise((resolve, reject) => {
        const waiter = {resolve, reject};
        if (writer.inFlight && writer.inFlight.categoryId === categoryId) {
          writer.inFlight.renderIntent ||= renderIntent;
          if (writer.pending && writer.pending.categoryId !== categoryId) {
            writer.pending.waiters.forEach(item => item.resolve(false));
            writer.pending = null;
          }
          writer.inFlight.waiters.push(waiter);
          return;
        }
        if (writer.pending && writer.pending.categoryId === categoryId) {
          writer.pending.renderIntent ||= renderIntent;
          writer.pending.waiters.push(waiter);
        } else {
          if (writer.pending) {
            writer.pending.waiters.forEach(item => item.resolve(false));
          }
          writer.pending = {categoryId, renderIntent, waiters: [waiter]};
        }
        drainConfirmationWriter(writer);
      });
    }

    function cancelConfirmationWrites(scanId) {
      const writer = confirmationWriters.get(scanId);
      if (!writer) return Promise.resolve();
      writer.latestCategory = null;
      if (writer.pending) {
        writer.pending.waiters.forEach(item => item.resolve(false));
        writer.pending = null;
      }
      if (!writer.inFlight) return Promise.resolve();
      return new Promise(resolve => writer.idleWaiters.push(resolve));
    }

    async function loadExplanation(scanId, expectedGeneration = generation) {
      try {
        const result = await api(`/api/v1/explain/${encodeURIComponent(scanId)}`, {
          method: "POST"
        });
        if (expectedGeneration !== generation || scanId !== activeScanId) return false;
        view.renderInfluence(result);
        return true;
      } catch (error) {
        if (expectedGeneration !== generation || scanId !== activeScanId) return false;
        view.renderInfluence({
          error: "Model influence is unavailable for this scan. The classification result is unchanged."
        });
        return false;
      }
    }

    async function loadHistory() {
      const requestedGeneration = ++historyGeneration;
      try {
        const records = await api("/api/v1/history");
        if (requestedGeneration !== historyGeneration) return [];
        view.renderHistory(Array.isArray(records) ? records : []);
        return records;
      } catch (error) {
        if (requestedGeneration !== historyGeneration) return [];
        view.renderHistory([], error.message);
        return [];
      }
    }

    function analysisIsCurrent(analysisGeneration) {
      return analysisGeneration === generation &&
        analysisGeneration === activeAnalysisGeneration;
    }

    function invalidateAnalysis() {
      generation += 1;
      assessmentGeneration += 1;
      activeAssessment = null;
      cancelAssessmentSave();
      activeScanId = null;
      if (activeAnalysisGeneration !== null) {
        activeAnalysisGeneration = null;
        view.setBusy(false);
      }
    }

    async function analyze(file) {
      if (activeAnalysisGeneration !== null) return false;
      if (!isSupportedImage(file)) {
        view.transition("error", {
          message: "Choose a JPEG, PNG, HEIC, or WebP image and try again."
        });
        return false;
      }

      const analysisGeneration = ++generation;
      activeAnalysisGeneration = analysisGeneration;
      activeScanId = null;
      view.setBusy(true);
      try {
        view.transition("decoding", {file});
        view.showPreview(objectUrl(file));
        await nextFrame();
        if (!analysisIsCurrent(analysisGeneration)) return false;

        const body = formDataFactory();
        body.append("image", file, file.name);
        const mass = typeof view.getMass === "function" ? view.getMass() : "";
        if (mass) body.append("mass_g", mass);

        view.transition("classifying", {file});
        const result = await api("/api/v1/classify", {method: "POST", body});
        if (!analysisIsCurrent(analysisGeneration)) return false;
        activeScanId = result.scan_id || null;
        activeResult = withModelEvidence(result);
        view.transition(result.low_confidence ? "review" : "result", activeResult);
        if (result.scan_id) void loadExplanation(result.scan_id, analysisGeneration);
        void loadHistory();
        return true;
      } catch (error) {
        if (!analysisIsCurrent(analysisGeneration)) return false;
        view.transition("error", {message: error.message});
        return false;
      } finally {
        if (activeAnalysisGeneration === analysisGeneration) {
          activeAnalysisGeneration = null;
          view.setBusy(false);
        }
      }
    }

    function cancelPhonePoll() {
      if (phonePollTimer === null) return;
      cancelSchedule(phonePollTimer);
      phonePollTimer = null;
    }

    function schedulePhonePoll(expectedGeneration = phoneGeneration) {
      if (!phoneActive || phonePollTimer !== null || expectedGeneration !== phoneGeneration) return;
      phonePollTimer = schedule(() => {
        phonePollTimer = null;
        if (phoneActive && expectedGeneration === phoneGeneration) {
          void pollPhoneSession(expectedGeneration);
        }
      }, phonePollDelay);
    }

    function consumePhoneResult(result) {
      invalidateAnalysis();
      activeScanId = result.scan_id || null;
      activeResult = withModelEvidence(result);
      if (typeof view.showSection === "function") view.showSection("scan");
      if (typeof view.clearPreview === "function") {
        view.clearPreview("This photo arrived from your phone over temporary same-network HTTP. The full-resolution image was not retained.");
      }
      view.transition(result.low_confidence ? "review" : "result", activeResult);
      if (typeof view.renderPhoneIncomingResult === "function") {
        view.renderPhoneIncomingResult(activeResult);
      }
      if (result.scan_id) void loadExplanation(result.scan_id, generation);
      void loadHistory();
    }

    async function startPhoneSession() {
      const requestedGeneration = ++phoneGeneration;
      phoneActive = false;
      cancelPhonePoll();
      if (typeof view.setPhoneState === "function") view.setPhoneState("starting");
      const request = api("/api/phone-session", {method: "POST"});
      phoneStartRequest = request;
      try {
        const session = await request;
        if (requestedGeneration !== phoneGeneration) return false;
        if (!session.active) throw new Error("The phone capture session did not start.");
        phoneActive = true;
        if (typeof view.setPhoneState === "function") view.setPhoneState("ready", session);
        if (typeof view.updatePhoneSession === "function") view.updatePhoneSession(session);
        schedulePhonePoll(requestedGeneration);
        return true;
      } catch (error) {
        if (requestedGeneration !== phoneGeneration) return false;
        phoneActive = false;
        if (typeof view.setPhoneState === "function") {
          view.setPhoneState("error", {message: error.message});
        }
        return false;
      } finally {
        if (phoneStartRequest === request) phoneStartRequest = null;
      }
    }

    async function pollPhoneSession(expectedGeneration = phoneGeneration) {
      cancelPhonePoll();
      if (!phoneActive || expectedGeneration !== phoneGeneration) return false;
      try {
        const session = await api("/api/phone-session", {method: "GET"});
        if (expectedGeneration !== phoneGeneration || !phoneActive) return false;
        if (typeof view.updatePhoneSession === "function") view.updatePhoneSession(session);
        if (session.result) {
          consumePhoneResult(session.result);
          if (typeof view.setPhoneState === "function") {
            view.setPhoneState("received", session);
          }
        }
        if (!session.active) {
          phoneActive = false;
          cancelPhonePoll();
          if (typeof view.setPhoneState === "function") {
            view.setPhoneState("expired", {
              message: "This temporary phone session expired. Start a new one to capture another photo."
            });
          }
          return true;
        }
        schedulePhonePoll(expectedGeneration);
        return true;
      } catch (error) {
        if (expectedGeneration !== phoneGeneration || !phoneActive) return false;
        phoneActive = false;
        cancelPhonePoll();
        if (typeof view.setPhoneState === "function") {
          view.setPhoneState("error", {message: error.message});
        }
        return false;
      }
    }

    async function stopPhoneSession() {
      phoneGeneration += 1;
      phoneActive = false;
      cancelPhonePoll();
      const pendingStart = phoneStartRequest;
      let stopped = true;
      try {
        await api("/api/phone-session", {method: "DELETE"});
      } catch (_error) {
        stopped = false;
      }
      if (pendingStart !== null) {
        try {
          await pendingStart;
        } catch (_error) {
          // The failed start has no listener to revoke.
        }
        try {
          await api("/api/phone-session", {method: "DELETE"});
          stopped = true;
        } catch (_error) {
          stopped = false;
        }
      }
      if (typeof view.setPhoneState === "function") view.setPhoneState("idle");
      return stopped;
    }

    async function commitDelete(scanId) {
      historyGeneration += 1;
      view.markHistoryDeleting(scanId);
      try {
        await cancelConfirmationWrites(scanId);
        await api(`/api/v1/history/${encodeURIComponent(scanId)}`, {method: "DELETE"});
        await loadHistory();
        return true;
      } catch (error) {
        if (typeof view.renderHistoryError === "function") view.renderHistoryError(`Could not delete this scan: ${error.message}`);
        return false;
      }
    }

    function stageHistoryAction(message, commit) {
      if (pendingHistoryAction) pendingHistoryAction.undo();
      if (undoDelay <= 0) return commit();
      const pending = {
        timer: null,
        undo() {
          if (!pending.timer) return;
          cancelSchedule(pending.timer);
          pending.timer = null;
          if (pendingHistoryAction === pending) pendingHistoryAction = null;
          if (typeof view.clearHistoryUndo === "function") view.clearHistoryUndo();
          void loadHistory();
        }
      };
      pendingHistoryAction = pending;
      if (typeof view.showHistoryUndo === "function") view.showHistoryUndo(message, pending.undo);
      pending.timer = schedule(() => {
        pending.timer = null;
        if (pendingHistoryAction === pending) pendingHistoryAction = null;
        if (typeof view.clearHistoryUndo === "function") view.clearHistoryUndo();
        void commit();
      }, undoDelay);
      return Promise.resolve(true);
    }

    function deleteHistory(scanId) {
      return stageHistoryAction("Scan will be deleted. Undo", () => commitDelete(scanId));
    }

    async function commitClear() {
      historyGeneration += 1;
      try {
        await Promise.all(
          Array.from(confirmationWriters.keys()).map(cancelConfirmationWrites)
        );
        await api("/api/v1/history", {method: "DELETE"});
        await loadHistory();
        return true;
      } catch (error) {
        if (typeof view.renderHistoryError === "function") view.renderHistoryError(`Could not clear history: ${error.message}`);
        return false;
      }
    }

    function clearHistory() {
      return stageHistoryAction("History will be cleared. Undo", commitClear);
    }

    function reset() {
      invalidateAnalysis();
      activeResult = null;
      view.transition("empty");
      if (typeof view.reset === "function") view.reset();
    }

    async function openAssessment() {
      if (typeof view.showSection === "function") view.showSection("assessment");
      const context = getAssessmentContext();
      cancelAssessmentSave();
      const requestedGeneration = ++assessmentGeneration;
      activeAssessment = null;
      if (!context || !context.scan_id) {
        if (typeof view.setAssessmentState === "function") {
          view.setAssessmentState("assessment-error", "Save a classification before starting an assessment.");
        }
        return false;
      }
      if (typeof view.setAssessmentState === "function") view.setAssessmentState("assessment-loading");
      try {
        const categories = await api("/api/v1/reference/categories");
        if (requestedGeneration !== assessmentGeneration) return false;
        try {
          const assessment = await api(`/api/v1/scans/${encodeURIComponent(context.scan_id)}/assessment`);
          if (requestedGeneration !== assessmentGeneration) return false;
          activeAssessment = {mode: "existing", categories, assessment, context};
          if (typeof view.renderAssessment === "function") view.renderAssessment(activeAssessment);
          if (typeof view.setAssessmentState === "function") {
            view.setAssessmentState("assessment-ready", `${formatCategory(assessment.category_id)} assessment ready.`);
          }
          return true;
        } catch (error) {
          if (error.status !== 409) throw error;
          const categoryId = context.confirmed_class_name;
          const template = await api(`/api/v1/reference/categories/${encodeURIComponent(categoryId)}`);
          if (requestedGeneration !== assessmentGeneration) return false;
          activeAssessment = {mode: "draft", categories, template, context};
          if (typeof view.renderAssessmentDraft === "function") view.renderAssessmentDraft(activeAssessment);
          if (typeof view.setAssessmentState === "function") view.setAssessmentState("assessment-editing");
          return true;
        }
      } catch (error) {
        if (requestedGeneration !== assessmentGeneration) return false;
        if (typeof view.setAssessmentState === "function") {
          view.setAssessmentState("assessment-error", error.message);
        }
        return false;
      }
    }

    async function changeAssessmentCategory(categoryId) {
      if (!activeAssessment || activeAssessment.mode !== "draft" || !categoryId) return false;
      let draftInputs = null;
      try {
        draftInputs = typeof view.readAssessmentForm === "function" ? view.readAssessmentForm() : null;
        if (draftInputs) draftInputs = {...draftInputs, component_overrides: {}};
      } catch (error) {
        if (typeof view.setAssessmentState === "function") view.setAssessmentState("assessment-editing");
        if (typeof view.showAssessmentFormError === "function") {
          view.showAssessmentFormError(error.message);
        }
        return false;
      }
      cancelAssessmentSave();
      const requestedGeneration = ++assessmentGeneration;
      if (typeof view.setAssessmentState === "function") view.setAssessmentState("assessment-loading");
      try {
        const template = await api(`/api/v1/reference/categories/${encodeURIComponent(categoryId)}`);
        if (requestedGeneration !== assessmentGeneration || !activeAssessment) return false;
        activeAssessment = {...activeAssessment, template, draft_inputs: draftInputs};
        if (typeof view.renderAssessmentDraft === "function") view.renderAssessmentDraft(activeAssessment);
        if (typeof view.setAssessmentState === "function") view.setAssessmentState("assessment-editing");
        return true;
      } catch (error) {
        if (requestedGeneration !== assessmentGeneration) return false;
        if (typeof view.setAssessmentState === "function") view.setAssessmentState("assessment-error", error.message);
        return false;
      }
    }

    function markAssessmentEditing() {
      if (activeAssessment && typeof view.setAssessmentState === "function") {
        view.setAssessmentState("assessment-editing");
      }
      if (typeof view.clearAssessmentFormError === "function") {
        view.clearAssessmentFormError();
      }
    }

    async function saveAssessment(form) {
      if (assessmentSaveToken !== null || !activeAssessment) return false;
      let context = activeAssessment.context;
      const scanId = context && context.scan_id;
      if (!scanId) return false;
      let payload;
      let categoryId;
      try {
        payload = view.readAssessmentForm(form);
        categoryId = view.getAssessmentCategory(form);
        const categories = Array.isArray(activeAssessment.categories) ? activeAssessment.categories : [];
        if (!categoryId || !categories.some(category => category.category_id === categoryId)) {
          throw new Error("Choose an available reference category.");
        }
      } catch (error) {
        if (typeof view.setAssessmentState === "function") view.setAssessmentState("assessment-editing");
        if (typeof view.showAssessmentFormError === "function") {
          view.showAssessmentFormError(error.message);
        }
        return false;
      }
      const requestedGeneration = ++assessmentGeneration;
      const saveToken = {};
      assessmentSaveToken = saveToken;
      if (typeof view.clearAssessmentFormError === "function") {
        view.clearAssessmentFormError();
      }
      if (typeof view.setAssessmentBusy === "function") view.setAssessmentBusy(true);
      if (typeof view.setAssessmentState === "function") view.setAssessmentState("assessment-loading");
      try {
        const confirmationRecord = await persistConfirmation(scanId, categoryId);
        if (!confirmationRecord) return false;
        if (requestedGeneration !== assessmentGeneration) return false;
        if (
          !activeResult ||
          activeResult.scan_id !== scanId ||
          activeResult.confirmed_class_name !== categoryId
        ) return false;
        context = getAssessmentContext();
        const assessment = await api(`/api/v1/scans/${encodeURIComponent(scanId)}/assessment`, {
          method: "PUT",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload)
        });
        if (requestedGeneration !== assessmentGeneration) return false;
        activeAssessment = {
          mode: "existing",
          categories: activeAssessment.categories,
          assessment,
          context
        };
        if (typeof view.renderAssessment === "function") view.renderAssessment(activeAssessment);
        if (typeof view.setAssessmentState === "function") {
          view.setAssessmentState("assessment-ready", `${formatCategory(assessment.category_id)} assessment updated.`);
        }
        return true;
      } catch (error) {
        if (requestedGeneration !== assessmentGeneration || assessmentSaveToken !== saveToken) return false;
        if (typeof view.setAssessmentState === "function") view.setAssessmentState("assessment-editing");
        if (typeof view.showAssessmentFormError === "function") {
          view.showAssessmentFormError(error.message);
        }
        return false;
      } finally {
        if (assessmentSaveToken === saveToken) {
          assessmentSaveToken = null;
          if (typeof view.setAssessmentBusy === "function") view.setAssessmentBusy(false);
        }
      }
    }

    function openHistory(record) {
      invalidateAnalysis();
      const prediction = record.prediction || {};
      const confirmation = record.confirmation || {};
      const confirmedClassName = confirmation.accepted_class_name;
      const modelResult = withModelEvidence({
        ...prediction,
        scan_id: record.scan_id,
        from_history: true,
        confirmed_class_name: confirmedClassName,
        confirmed_confidence: confirmedClassName ? selectedModelScore({
          ...prediction,
          model_class_name: prediction.class_name,
          model_confidence: prediction.confidence
        }, confirmedClassName) : undefined,
        confirmation_source: confirmation.source
      });
      const writer = confirmationWriter(record.scan_id);
      if (writer.committedResult) {
        activeResult = {...writer.committedResult};
      } else {
        activeResult = modelResult;
        writer.committedResult = {...activeResult};
      }
      view.showSection("scan");
      view.clearPreview("The source image is unavailable for this history record.");
      view.transition(prediction.low_confidence ? "review" : "result", activeResult);
      view.renderInfluence({
        error: (
          "The source image is unavailable for this history record. " +
          "Model influence is available only immediately after a new classification."
        )
      });
    }

    function selectAlternative(candidate) {
      if (!activeResult) return false;
      const selected = (activeResult.topk || []).find(
        item => item.class_name === candidate.class_name
      );
      if (!selected || selected.class_name === activeResult.model_class_name) return false;
      if (activeResult.scan_id) {
        seedConfirmationWriter(activeResult.scan_id, activeResult);
      }
      activeResult = {
        ...activeResult,
        confirmed_class_name: selected.class_name,
        confirmed_confidence: selected.confidence,
        confirmation_source: "user"
      };
      view.renderCorrection({
        scan_id: activeResult.scan_id || null,
        model_class_name: activeResult.model_class_name,
        model_confidence: activeResult.model_confidence,
        confirmed_class_name: activeResult.confirmed_class_name,
        confirmed_confidence: activeResult.confirmed_confidence,
        confirmation_source: activeResult.confirmation_source
      });
      if (activeResult.scan_id) {
        void persistConfirmation(
          activeResult.scan_id, selected.class_name, true
        ).catch(() => {});
      }
      return true;
    }

    function getAssessmentContext() {
      if (!activeResult) return null;
      return {
        scan_id: activeResult.scan_id || null,
        confirmed_class_name: activeResult.confirmed_class_name,
        model_evidence: {
          class_name: activeResult.model_class_name,
          confidence: activeResult.model_confidence
        },
        confirmation: {
          source: activeResult.confirmation_source,
          selected_model_score: activeResult.confirmed_confidence
        }
      };
    }

    if (typeof view.setAlternativeHandler === "function") {
      view.setAlternativeHandler(selectAlternative);
    }

    return {
      analyze, changeAssessmentCategory, clearHistory, deleteHistory, getAssessmentContext,
      loadExplanation, loadHistory, markAssessmentEditing, openAssessment, openHistory,
      pollPhoneSession, reset, saveAssessment, selectAlternative, startPhoneSession,
      stopPhoneSession
    };
  }

  function createReleaseAboutController(options) {
    const view = options.view;
    const fetchImpl = options.fetchImpl;
    let cached = null;
    let generation = 0;
    let request = null;

    function isDisplayMetadata(value) {
      return value && typeof value === "object" &&
        Object.keys(value).length === 5 &&
        ["app_version", "source_revision", "model_sha256", "component_database_sha256", "component_database_version"]
          .every(key => typeof value[key] === "string");
    }

    async function load(force = false) {
      if (cached && !force) {
        view.setReleaseState("ready", cached);
        return true;
      }
      if (request && !force) return request;
      const requestedGeneration = ++generation;
      view.setReleaseState("loading");
      const pending = Promise.resolve(fetchImpl("/api/v1/release-metadata"))
        .then(responseJson)
        .then(payload => {
          if (!isDisplayMetadata(payload)) throw new Error("Release metadata is unavailable.");
          if (requestedGeneration !== generation) return false;
          cached = payload;
          view.setReleaseState("ready", payload);
          return true;
        })
        .catch(error => {
          if (requestedGeneration !== generation) return false;
          view.setReleaseState("error", {message: error.message});
          return false;
        })
        .finally(() => {
          if (request === pending) request = null;
        });
      request = pending;
      return pending;
    }

    function close() {
      generation += 1;
      request = null;
    }

    return {open: () => load(false), retry: () => load(true), close};
  }

  function element(document, tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function createDomView(document) {
    const html = document.documentElement;
    const stateFrame = document.getElementById("state-frame");
    const live = document.getElementById("live-status");
    const progressImage = document.getElementById("progress-image");
    const resultImage = document.getElementById("result-image");
    const progressPlaceholder = document.getElementById("preview-placeholder");
    const resultPlaceholder = document.getElementById("result-placeholder");
    const resultCategory = document.getElementById("result-category");
    const categoryLabel = document.getElementById("category-label");
    const resultBadge = document.getElementById("result-badge");
    const scanSaved = document.getElementById("scan-saved");
    const confidenceNumber = document.getElementById("confidence-number");
    const confidenceLabel = document.getElementById("confidence-label");
    const confidenceBar = document.getElementById("confidence-bar");
    const alternativesList = document.getElementById("alternatives-list");
    const selectionNote = document.getElementById("selection-note");
    const influenceGrid = document.getElementById("influence-grid");
    const influenceCopy = document.getElementById("influence-copy");
    const influenceToggleRow = document.getElementById("influence-toggle-row");
    const influenceToggle = document.getElementById("influence-toggle");
    const imageStage = document.querySelector(".image-stage");
    const valuation = document.getElementById("valuation");
    const historyWarning = document.getElementById("history-warning");
    const historyList = document.getElementById("history-list");
    const historyEmpty = document.getElementById("history-empty");
    const historyUndo = document.getElementById("history-undo");
    const historyUndoMessage = document.getElementById("history-undo-message");
    const historyUndoButton = document.getElementById("history-undo-button");
    const assessmentFrame = document.getElementById("assessment-frame");
    const assessmentForm = document.getElementById("assessment-form");
    const assessmentSaveFeedback = document.getElementById("assessment-save-feedback");
    const assessmentCategory = document.getElementById("assessment-category");
    const assessmentComponents = document.getElementById("assessment-components");
    const assessmentSafetyList = document.getElementById("assessment-safety-list");
    const assessmentEvidenceList = document.getElementById("assessment-evidence-list");
    const phoneDialog = document.getElementById("phone-dialog");
    const phoneQr = document.getElementById("phone-qr");
    const phonePairingCode = document.getElementById("phone-pairing-code");
    const phoneCountdown = document.getElementById("phone-countdown");
    const phoneCountdownRing = document.querySelector(".phone-countdown-ring");
    const phoneErrorTitle = document.getElementById("phone-error-title");
    const phoneErrorMessage = document.getElementById("phone-error-message");
    const phoneIncomingCategory = document.getElementById("phone-incoming-category");
    const releaseStatus = document.getElementById("release-about-status");
    const releaseValues = {
      app_version: document.getElementById("release-app-version"),
      source_revision: document.getElementById("release-source-revision"),
      model_sha256: document.getElementById("release-model-sha256"),
      component_database_sha256: document.getElementById("release-component-sha256"),
      component_database_version: document.getElementById("release-component-version")
    };
    let previewUrl = "";
    let activeResult = null;
    let alternativeHandler = null;
    let phoneSessionDuration = 600;

    function announce(message) {
      live.textContent = "";
      global.setTimeout(() => { live.textContent = message; }, 0);
    }

    function setBusy(value) {
      stateFrame.setAttribute("aria-busy", String(value));
      for (const control of document.querySelectorAll("[data-submit]")) {
        control.disabled = value;
      }
      document.getElementById("photo-input").disabled = value;
    }

    function updatePhoneSession(session) {
      const remaining = Math.max(0, Number(session && session.expires_in_seconds) || 0);
      if (remaining > phoneSessionDuration) phoneSessionDuration = remaining;
      const wholeSeconds = Math.ceil(remaining);
      const minutes = Math.floor(wholeSeconds / 60);
      const seconds = wholeSeconds % 60;
      phoneCountdown.textContent = `${minutes}:${String(seconds).padStart(2, "0")}`;
      phoneCountdown.dateTime = `PT${wholeSeconds}S`;
      phoneCountdownRing.style.setProperty(
        "--phone-progress",
        String(Math.max(0, Math.min(1, remaining / phoneSessionDuration)))
      );
    }

    function setPhoneState(state, payload = {}) {
      phoneDialog.dataset.phoneState = state;
      if ((state === "ready" || state === "received") && payload.qr_png) {
        phoneSessionDuration = Math.max(
          1,
          Number(payload.expires_in_seconds) || 600
        );
        phoneQr.src = payload.qr_png;
      }
      if ((state === "ready" || state === "received") && payload.pairing_code) {
        phonePairingCode.textContent = String(payload.pairing_code).replace(
          /^(\d{2})(\d{2})(\d{2})$/,
          "$1 $2 $3"
        );
      }
      if (state === "starting") {
        phoneErrorMessage.textContent = "Check that both devices are on the same Wi-Fi network, then try again.";
        announce("Starting a temporary phone capture session.");
      } else if (state === "ready") {
        announce("Phone capture is ready. Scan the QR code, then enter the six-digit pairing code.");
      } else if (state === "expired" || state === "error") {
        phoneErrorTitle.textContent = state === "expired" ?
          "Phone session expired" : "Phone capture unavailable";
        phoneErrorMessage.textContent = payload.message ||
          "Check that both devices are on the same Wi-Fi network, then try again.";
        announce(phoneErrorMessage.textContent);
      } else if (state === "idle") {
        phoneQr.removeAttribute("src");
        phonePairingCode.textContent = "—— —— ——";
        phoneSessionDuration = 600;
        updatePhoneSession({expires_in_seconds: phoneSessionDuration});
      }
    }

    function setReleaseState(state, payload = {}) {
      const dialog = document.getElementById("release-about-dialog");
      dialog.dataset.releaseState = state;
      if (state === "loading") {
        releaseStatus.textContent = "Loading release information.";
        return;
      }
      if (state === "error") {
        releaseStatus.textContent = payload.message || "Release information is unavailable. Try again.";
        return;
      }
      for (const [name, target] of Object.entries(releaseValues)) {
        target.textContent = payload[name];
      }
      releaseStatus.textContent = "Release information is ready.";
    }

    function renderPhoneIncomingResult(result) {
      phoneIncomingCategory.textContent = formatCategory(
        result.confirmed_class_name || result.class_name
      );
      announce(`${phoneIncomingCategory.textContent} photo received from your phone.`);
    }

    function showPreview(url) {
      previewUrl = url;
      for (const image of [progressImage, resultImage]) {
        image.src = url;
        image.hidden = false;
      }
      progressPlaceholder.hidden = true;
      resultPlaceholder.hidden = true;
    }

    function clearPreview(message) {
      if (previewUrl) global.URL.revokeObjectURL(previewUrl);
      previewUrl = "";
      for (const image of [progressImage, resultImage]) {
        image.removeAttribute("src");
        image.hidden = true;
      }
      progressPlaceholder.hidden = false;
      resultPlaceholder.hidden = false;
      resultPlaceholder.textContent = "Photo unavailable";
      influenceCopy.textContent = message;
    }

    function renderAlternatives(result) {
      alternativesList.replaceChildren();
      const candidates = (Array.isArray(result.topk) ? result.topk : [])
        .filter(item => item.class_name !== result.class_name)
        .slice(0, 3);
      if (!candidates.length) {
        alternativesList.append(element(document, "p", "selection-note", "No other category scored strongly enough to show."));
        return;
      }
      for (const item of candidates) {
        const button = element(document, "button", "alternative");
        button.type = "button";
        button.dataset.category = item.class_name;
        button.setAttribute("aria-pressed", "false");
        button.append(
          element(document, "strong", "", formatCategory(item.class_name)),
          element(document, "span", "", percent(item.confidence))
        );
        button.addEventListener("click", () => {
          if (alternativeHandler) alternativeHandler(item);
        });
        alternativesList.append(button);
      }
    }

    function renderValuation(result) {
      if (!result.valuation) {
        valuation.hidden = true;
        return;
      }
      const value = result.valuation;
      valuation.hidden = false;
      document.getElementById("valuation-value").textContent = currency(value.value_usd);
      document.getElementById("valuation-range").textContent =
        `${currency(value.value_low)}–${currency(value.value_high)} range`;
      document.getElementById("valuation-detail").textContent =
        `${Number(value.mass_kg || 0).toFixed(3)} kg (${value.mass_source || "estimated"}) · prices ${value.prices_quoted_date || "bundled"}`;
    }

    function renderResult(result) {
      activeResult = result;
      resultCategory.textContent = formatCategory(result.confirmed_class_name || result.class_name);
      categoryLabel.textContent = result.confirmation_source === "user" ?
        "Confirmed category" : "Likely category";
      resultBadge.textContent = result.confirmation_source === "user" ?
        "User correction" : result.low_confidence ? "Needs review" : "Classified";
      scanSaved.textContent = result.from_history ? "From history" :
        result.scan_id ? "Saved locally" : "Not saved";
      confidenceLabel.textContent = result.confirmation_source === "user" ?
        "Original model confidence" : "Model confidence";
      confidenceNumber.textContent = percent(result.model_confidence ?? result.confidence);
      confidenceBar.style.setProperty("--confidence", String(Math.max(0, Math.min(1, Number(result.model_confidence ?? result.confidence) || 0))));
      historyWarning.hidden = !result.history_error;
      historyWarning.textContent = result.history_error || "";
      selectionNote.hidden = true;
      influenceToggleRow.hidden = true;
      influenceToggle.checked = false;
      imageStage.dataset.influence = "false";
      influenceCopy.textContent = result.from_history ?
        "The source image is unavailable for this history record. Model influence is available only immediately after a new classification." :
        result.scan_id ? "The optional model influence view is loading." :
          "This result was not saved, so model influence is unavailable.";
      renderAlternatives(result);
      renderValuation(result);
      if (result.confirmation_source === "user") renderCorrection(result, false);
    }

    function renderCorrection(correction, shouldAnnounce = true) {
      resultCategory.textContent = formatCategory(correction.confirmed_class_name);
      categoryLabel.textContent = "Confirmed category";
      resultBadge.textContent = "User correction";
      confidenceLabel.textContent = "Original model confidence";
      confidenceNumber.textContent = percent(correction.model_confidence);
      confidenceBar.style.setProperty("--confidence", String(Math.max(0, Math.min(1, Number(correction.model_confidence) || 0))));
      for (const option of alternativesList.querySelectorAll(".alternative")) {
        option.setAttribute("aria-pressed", String(
          option.dataset.category === correction.confirmed_class_name
        ));
      }
      selectionNote.hidden = false;
      const confirmationCopy =
        `Confirmed as ${formatCategory(correction.confirmed_class_name)}. ` +
        `The model originally predicted ${formatCategory(correction.model_class_name)} ` +
        `at ${percent(correction.model_confidence)}.`;
      if (correction.confirmed_class_name === correction.model_class_name) {
        selectionNote.textContent = `${confirmationCopy} The user confirmed the model prediction.`;
      } else if (
        typeof correction.confirmed_confidence === "number" &&
        Number.isFinite(correction.confirmed_confidence)
      ) {
        selectionNote.textContent =
          `${confirmationCopy} This displayed alternative scored ` +
          `${percent(correction.confirmed_confidence)}.`;
      } else {
        selectionNote.textContent =
          `${confirmationCopy} The confirmed category was not among the model alternatives ` +
          "displayed, so no model score is available.";
      }
      if (shouldAnnounce) {
        announce(`${formatCategory(correction.confirmed_class_name)} confirmed as a user correction.`);
      }
    }

    function transition(state, payload = {}) {
      html.dataset.state = state;
      if (state === "result" || state === "review") renderResult(payload);
      if (state === "error") {
        document.getElementById("error-message").textContent = payload.message ||
          "Choose a supported image and try again.";
      }
      const confirmedResultMessage = payload.confirmation_source === "user" ?
        `${formatCategory(payload.confirmed_class_name)} opened as a user-confirmed category.` :
        `Classification complete: ${formatCategory(payload.class_name)}.`;
      const messages = {
        empty: "Ready for a device photo.",
        decoding: "Preparing the selected photo.",
        classifying: "Classifying the device locally.",
        result: confirmedResultMessage,
        review: payload.confirmation_source === "user" ?
          confirmedResultMessage :
          "Classification complete with low confidence. Review the leading categories.",
        error: payload.message || "The scan could not be completed."
      };
      announce(messages[state] || "");
    }

    function renderInfluence(result) {
      influenceGrid.replaceChildren();
      if (result.error) {
        influenceToggleRow.hidden = true;
        influenceCopy.textContent = result.error;
        return;
      }
      const values = Array.isArray(result.values) ? result.values : [];
      influenceGrid.style.setProperty("--grid-size", String(result.grid_size || values.length || 7));
      for (const row of values) {
        for (const value of row) {
          const cell = element(document, "span", "influence-cell");
          cell.style.setProperty("--influence", String(Math.max(0, Math.min(0.72, Number(value) * 0.72))));
          influenceGrid.append(cell);
        }
      }
      influenceGrid.hidden = false;
      influenceToggleRow.hidden = false;
      influenceCopy.textContent = `${result.copy || "Regions that influenced this result."} The overlay does not detect components or indicate condition.`;
      announce("The optional model influence view is ready.");
    }

    function renderHistory(records, errorMessage) {
      historyList.replaceChildren();
      historyEmpty.hidden = records.length > 0;
      if (errorMessage) {
        historyEmpty.hidden = false;
        historyEmpty.querySelector("h2").textContent = "History is unavailable";
        historyEmpty.querySelector("p").textContent = errorMessage;
        return;
      }
      records.forEach((record, index) => {
        const prediction = record.prediction || {};
        const presentation = historyPresentation(record);
        const item = element(document, "li", "history-item");
        item.dataset.scanId = record.scan_id;
        item.style.animationDelay = `${Math.min(index * 35, 105)}ms`;
        item.append(element(document, "span", "history-glyph", "⌁"));
        const copy = element(document, "span", "history-copy");
        copy.append(
          element(document, "strong", "", presentation.category),
          element(document, "small", "", `${presentation.model_evidence} · ${new Date(record.created_at).toLocaleString()}`)
        );
        const review = element(document, "button", "history-action", "Review");
        review.type = "button";
        review.dataset.historyReview = record.scan_id;
        const remove = element(document, "button", "history-action delete", "Delete");
        remove.type = "button";
        remove.dataset.historyDelete = record.scan_id;
        item.append(copy, review, remove);
        item._record = record;
        historyList.append(item);
      });
    }

    function markHistoryDeleting(scanId) {
      const item = Array.from(historyList.children).find(node => node.dataset.scanId === scanId);
      if (item) item.dataset.deleting = "true";
      announce("Deleting scan from local history.");
    }

    function showHistoryUndo(message, undo) {
      historyUndoMessage.textContent = message;
      historyUndo.hidden = false;
      historyUndoButton.onclick = undo;
      announce(message);
    }

    function clearHistoryUndo() {
      historyUndo.hidden = true;
      historyUndoButton.onclick = null;
    }

    function renderHistoryError(message) {
      historyEmpty.hidden = false;
      historyEmpty.querySelector("h2").textContent = "History action failed";
      historyEmpty.querySelector("p").textContent = message;
      announce(message);
    }

    function selectOption(value, label) {
      const option = element(document, "option", "", label);
      option.value = value;
      return option;
    }

    function setSelectOptions(select, options, value) {
      select.replaceChildren(...options.map(option => selectOption(option.value, option.label)));
      select.value = value || options[0].value;
    }

    function renderEvidenceRows(assessment, presentation, context) {
      assessmentEvidenceList.replaceChildren();
      const model = context && context.model_evidence;
      const rows = [
        ["Category", model ? `${formatCategory(model.class_name)} at ${percent(model.confidence)} model confidence` : presentation.category_name],
        ["Identification", context && context.confirmation && context.confirmation.source === "user" ? "User confirmed or corrected" : "Awaiting user confirmation"],
        ["Template", `${presentation.category_name} · revision ${presentation.template_version}`],
        ...presentation.input_evidence.map(item => [item.label, item.value])
      ];
      for (const [term, detail] of rows) {
        const wrapper = element(document, "div", "evidence-row");
        wrapper.append(element(document, "dt", "", term), element(document, "dd", "", detail));
        assessmentEvidenceList.append(wrapper);
      }
    }

    function renderSafety(presentation) {
      assessmentSafetyList.replaceChildren();
      if (!presentation.safety.length) {
        assessmentSafetyList.append(element(document, "p", "safety-empty", "No category-specific safety rule is attached. Continue with ordinary electronics handling care."));
        return;
      }
      presentation.safety.forEach(item => {
        const callout = element(document, "article", `safety-callout safety-${item.priority}`);
        if (item.priority === "escalation") {
          callout.setAttribute("role", "alert");
          callout.setAttribute("aria-label", "Safety escalation");
        }
        callout.append(
          element(document, "span", "safety-symbol", item.priority === "escalation" ? "!" : "i"),
          element(document, "p", "", item.text)
        );
        const source = element(document, "small", "", item.source_label);
        callout.append(source);
        assessmentSafetyList.append(callout);
      });
    }

    function labeledSelect(labelText, name, options, value) {
      const label = element(document, "label", "component-control");
      label.append(element(document, "span", "", labelText));
      const select = element(document, "select");
      select.name = name;
      setSelectOptions(select, options, value);
      label.append(select);
      return label;
    }

    function lifecycleOverrideControls(componentId, override) {
      const lifecycle = override.lifecycle || {};
      const fieldset = element(document, "fieldset", "component-lifecycle-override");
      fieldset.append(element(document, "legend", "", "Documented item lifecycle reference"));
      const metricControl = labeledSelect("Unit", `component.${componentId}.lifecycle_metric`, [
        {value: "", label: "No item override"},
        {value: "years", label: "Years"},
        {value: "cycles", label: "Cycles"},
        {value: "cycles_to_capacity", label: "Cycles to capacity"}
      ], lifecycle.metric || "");
      const metric = metricControl.querySelector("select");
      fieldset.append(metricControl);
      const range = element(document, "div", "component-range-inputs");
      const rangeInputs = [];
      for (const [suffix, labelText, value] of [
        ["min", "From", lifecycle.minimum], ["max", "To", lifecycle.maximum]
      ]) {
        const label = element(document, "label", "component-control");
        label.append(element(document, "span", "", labelText));
        const input = element(document, "input");
        input.type = "number";
        input.inputMode = "numeric";
        input.min = "1";
        input.step = "1";
        input.name = `component.${componentId}.lifecycle_${suffix}`;
        input.value = value === undefined ? "" : String(value);
        label.append(input);
        range.append(label);
        rangeInputs.push(input);
      }
      const capacityLabel = element(document, "label", "component-control");
      capacityLabel.append(element(document, "span", "", "Capacity threshold"));
      const capacity = element(document, "input");
      capacity.type = "number";
      capacity.inputMode = "numeric";
      capacity.min = "1";
      capacity.max = "100";
      capacity.step = "1";
      capacity.name = `component.${componentId}.lifecycle_capacity`;
      capacity.value = lifecycle.capacity_percent === undefined ? "" : String(lifecycle.capacity_percent);
      capacity.setAttribute("aria-label", "Capacity threshold percent");
      capacityLabel.append(capacity);
      range.append(capacityLabel);

      function syncLifecycleFields(clearInapplicable) {
        const hasLifecycle = Boolean(metric.value);
        const usesCapacity = metric.value === "cycles_to_capacity";
        for (const input of rangeInputs) {
          input.disabled = !hasLifecycle;
          input.max = metric.value === "years" ? "100" : "1000000";
          if (clearInapplicable && !hasLifecycle) input.value = "";
        }
        capacity.disabled = !usesCapacity;
        if (clearInapplicable && !usesCapacity) capacity.value = "";
      }

      metric.addEventListener("change", () => syncLifecycleFields(true));
      syncLifecycleFields(false);
      fieldset.append(range);
      fieldset.append(element(document, "p", "field-help", "Item-provided lifecycle references remain unverified and do not create a sourced health estimate."));
      return fieldset;
    }

    function renderComponents(assessment, presentation) {
      assessmentComponents.replaceChildren();
      const overrides = assessment.component_overrides || {};
      presentation.components.forEach((component, index) => {
        const override = overrides[component.component_id] || {};
        const row = element(document, "article", "component-row");
        row.style.setProperty("--component-index", String(Math.min(index, 3)));
        if (component.safety_sensitive) row.dataset.safetySensitive = "true";
        const header = element(document, "div", "component-row-header");
        const identity = element(document, "div", "component-identity");
        identity.append(
          element(document, "h3", "", component.display_name),
          element(document, "span", "presence-label", `${String(component.presence_label || "unknown").replace(/_/g, " ")} in category`)
        );
        const estimate = element(document, "div", "component-estimate");
        estimate.append(element(document, "strong", "", component.range), element(document, "span", "", component.confidence_label));
        header.append(identity, estimate);

        const recommendation = element(document, "div", "component-recommendation");
        recommendation.append(
          element(document, "span", "recommendation-mark", component.result && component.result.recommendation === "specialist_handling" ? "!" : "→"),
          element(document, "strong", "", component.recommendation_label)
        );
        const reason = element(document, "p", "component-reason", component.missing_guidance || component.reasons.join(" "));
        const reference = element(document, "p", "component-reference", `${component.reference_range} · ${component.lifecycle_source_label}`);

        const evidence = element(document, "ul", "component-evidence");
        for (const item of component.evidence) {
          const sources = Array.isArray(item.source_ids) && item.source_ids.length ? ` · ${item.source_ids.join(", ")}` : "";
          evidence.append(element(document, "li", "", `${item.detail}${sources}`));
        }

        const details = element(document, "details", "component-override");
        details.append(element(document, "summary", "", "Item override"));
        const controls = element(document, "div", "component-override-controls");
        controls.append(
          labeledSelect("Presence", `component.${component.component_id}.presence`, [
            {value: "", label: "Use category default"},
            {value: "standard", label: "Standard"},
            {value: "common", label: "Common"},
            {value: "optional", label: "Optional"},
            {value: "unknown", label: "Unknown"}
          ], override.presence_label || ""),
          labeledSelect("Component condition", `component.${component.component_id}.condition`, [
            {value: "", label: "Use device condition"},
            {value: "unknown", label: "Unknown"},
            {value: "no_visible_damage", label: "No visible damage"},
            {value: "visible_wear", label: "Visible wear"},
            {value: "damaged", label: "Damaged"}
          ], override.condition || ""),
          lifecycleOverrideControls(component.component_id, override)
        );
        details.append(controls);
        row.append(header, recommendation, reason, reference);
        if (component.evidence.length) row.append(evidence);
        row.append(details);
        assessmentComponents.append(row);
      });
    }

    function populateAssessment({assessment, categories, context, locked}) {
      clearAssessmentFormError();
      const presentation = buildAssessmentPresentation(assessment);
      const categoryId = assessment.category_id || assessment.template.category_id;
      setSelectOptions(assessmentCategory, categories.map(category => ({
        value: category.category_id,
        label: category.display_name || formatCategory(category.category_id)
      })), categoryId);
      assessmentCategory.disabled = locked;
      assessmentCategory.setAttribute("aria-describedby", "assessment-category-help");
      document.getElementById("assessment-category-lock").hidden = !locked;
      document.getElementById("assessment-category-help").textContent = locked ?
        "The confirmed category is locked to preserve this item’s reference snapshot." :
        "You can correct this before the first assessment snapshot is saved.";
      const inputs = assessment.inputs || {};
      for (const [id, value] of [
        ["assessment-age-min", inputs.age_months && inputs.age_months.minimum],
        ["assessment-age-max", inputs.age_months && inputs.age_months.maximum],
        ["assessment-cycles-min", inputs.cycle_count && inputs.cycle_count.minimum],
        ["assessment-cycles-max", inputs.cycle_count && inputs.cycle_count.maximum]
      ]) document.getElementById(id).value = value === null || value === undefined ? "" : String(value);
      document.getElementById("assessment-usage").value = inputs.usage || "unknown";
      document.getElementById("assessment-condition").value = inputs.condition || "unknown";
      document.getElementById("assessment-operational").value = inputs.operational || "unknown";
      const knownIssues = inputs.known_issues || {};
      for (const [id, name] of [
        ["assessment-issue-overheating", "overheating"],
        ["assessment-issue-odor", "odor"],
        ["assessment-issue-swelling", "swelling_or_battery_damage"],
        ["assessment-issue-recall", "recall"]
      ]) {
        document.getElementById(id).checked = knownIssues[name] === true;
      }
      document.getElementById("assessment-issue-notes").value = knownIssues.notes || "";
      document.getElementById("assessment-overall-range").textContent = presentation.overall_range;
      document.getElementById("assessment-overall-detail").textContent = presentation.overall_detail;
      document.getElementById("assessment-meter-fill").style.setProperty("--assessment-range", String(Math.min(100, presentation.overall_maximum) / 100));
      document.getElementById("assessment-template-version").textContent = `Revision ${presentation.template_version}`;
      renderEvidenceRows(assessment, presentation, context);
      renderSafety(presentation);
      renderComponents(assessment, presentation);
    }

    function draftAssessment(template, inputs) {
      return {
        category_id: template.category_id,
        template_version: template.template_version,
        template,
        inputs: inputs || {
          age_months: null,
          cycle_count: null,
          usage: "unknown",
          condition: "unknown",
          operational: "unknown",
          known_issues: {
            overheating: false,
            odor: false,
            swelling_or_battery_damage: false,
            recall: false,
            notes: null
          }
        },
        component_overrides: {},
        components: (template.components || []).map(component => ({
          ...component,
          result: {
            percent_used: null,
            confidence: "unavailable",
            recommendation: "unknown",
            reasons: component.lifecycle ?
              [`A user-supplied ${component.lifecycle.metric === "years" ? "age range" : "cycle-count range"} is required for this sourced lifecycle estimate.`] :
              ["No supported lifecycle reference is available for this component."],
            evidence: []
          }
        }))
      };
    }

    function renderAssessmentDraft(value) {
      populateAssessment({
        assessment: draftAssessment(value.template, value.draft_inputs),
        categories: value.categories,
        context: value.context,
        locked: false
      });
    }

    function renderAssessment(value) {
      populateAssessment({assessment: value.assessment, categories: value.categories, context: value.context, locked: true});
    }

    function readAssessmentForm(form) {
      return assessmentPayloadFromValues(Object.fromEntries(new global.FormData(form || assessmentForm).entries()));
    }

    function setAssessmentBusy(value) {
      document.getElementById("save-assessment").disabled = value;
      assessmentFrame.setAttribute("aria-busy", String(value));
    }

    function clearAssessmentFormError() {
      assessmentSaveFeedback.hidden = true;
      assessmentSaveFeedback.textContent = "";
    }

    function showAssessmentFormError(message) {
      assessmentSaveFeedback.textContent = message || "The assessment could not be saved. Review your entries and try again.";
      assessmentSaveFeedback.hidden = false;
      assessmentSaveFeedback.focus();
    }

    function setAssessmentState(state, message) {
      assessmentFrame.dataset.assessmentState = state;
      assessmentFrame.setAttribute("aria-busy", String(state === "assessment-loading"));
      if (state === "assessment-error") {
        document.getElementById("assessment-error-message").textContent = message || "Return to Scan and choose a saved result.";
      }
      if ((state === "assessment-ready" || state === "assessment-error") && message) announce(message);
    }

    function showSection(section) {
      for (const name of ["scan", "assessment", "history"]) {
        document.getElementById(`${name}-view`).hidden = name !== section;
      }
      if (section === "assessment") document.getElementById("assessment-view").focus();
      for (const link of document.querySelectorAll("[data-view-link]")) {
        if (link.classList.contains("nav-item")) {
          const selected = link.dataset.viewLink === section;
          link.classList.toggle("is-selected", selected);
          if (selected) link.setAttribute("aria-current", "page");
          else link.removeAttribute("aria-current");
        }
      }
    }

    function reset() {
      document.getElementById("photo-input").value = "";
      if (previewUrl) global.URL.revokeObjectURL(previewUrl);
      previewUrl = "";
      activeResult = null;
      progressImage.hidden = true;
      resultImage.hidden = true;
      progressPlaceholder.hidden = false;
      resultPlaceholder.hidden = false;
      influenceGrid.replaceChildren();
      influenceGrid.hidden = true;
      document.getElementById("drop-target").focus();
    }

    influenceToggle.addEventListener("change", () => {
      imageStage.dataset.influence = String(influenceToggle.checked);
      announce(influenceToggle.checked ? "Model influence overlay shown." : "Model influence overlay hidden.");
    });

    return {
      getMass: () => "",
      markHistoryDeleting,
      clearAssessmentFormError,
      clearHistoryUndo,
      clearPreview,
      getAssessmentCategory: () => assessmentCategory.value,
      renderCorrection,
      readAssessmentForm,
      renderAssessment,
      renderAssessmentDraft,
      renderHistory,
      renderHistoryError,
      renderInfluence,
      renderPhoneIncomingResult,
      reset,
      setBusy,
      setAssessmentBusy,
      setAssessmentState,
      setPhoneState,
      setReleaseState,
      showPreview,
      showAssessmentFormError,
      showHistoryUndo,
      showSection,
      updatePhoneSession,
      setAlternativeHandler(handler) { alternativeHandler = handler; },
      transition,
      get activeResult() { return activeResult; }
    };
  }

  function bootstrap(document) {
    const view = createDomView(document);
    const controller = createController({
      view,
      fetchImpl: global.fetch.bind(global),
      formDataFactory: () => new global.FormData(),
      nextFrame: () => new Promise(resolve => global.requestAnimationFrame(() => resolve())),
      objectUrl: file => global.URL.createObjectURL(file)
    });
    const input = document.getElementById("photo-input");
    const dropTarget = document.getElementById("drop-target");
    const phoneDialog = document.getElementById("phone-dialog");
    const releaseDialog = document.getElementById("release-about-dialog");
    const releaseController = createReleaseAboutController({
      view,
      fetchImpl: global.fetch.bind(global)
    });
    let releaseOpener = null;

    input.addEventListener("change", () => {
      if (input.files && input.files[0]) void controller.analyze(input.files[0]);
    });

    dropTarget.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        input.click();
      }
    });

    let dragDepth = 0;
    document.addEventListener("dragenter", event => {
      if (!event.dataTransfer || !Array.from(event.dataTransfer.types || []).includes("Files")) return;
      event.preventDefault();
      dragDepth += 1;
      dropTarget.dataset.drag = "true";
    });
    document.addEventListener("dragover", event => {
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
      event.preventDefault();
    });
    document.addEventListener("dragleave", () => {
      dragDepth = Math.max(0, dragDepth - 1);
      if (!dragDepth) dropTarget.dataset.drag = "false";
    });
    document.addEventListener("drop", event => {
      event.preventDefault();
      dragDepth = 0;
      dropTarget.dataset.drag = "false";
      const file = event.dataTransfer && event.dataTransfer.files[0];
      if (file) void controller.analyze(file);
    });

    document.addEventListener("click", event => {
      const viewLink = event.target.closest("[data-view-link]");
      if (viewLink) {
        event.preventDefault();
        const section = viewLink.dataset.viewLink;
        if (section === "assessment") {
          void controller.openAssessment();
        } else {
          view.showSection(section);
          if (section === "history") void controller.loadHistory();
        }
      }
      const phoneAction = event.target.closest("[data-phone-action], #phone-capture");
      if (phoneAction) {
        if (!phoneDialog.open) phoneDialog.showModal();
        void controller.startPhoneSession();
      }
      const closePhone = event.target.closest("[data-close-phone], #phone-stop, #phone-view-result");
      if (closePhone) phoneDialog.close();
      const openReleaseAbout = event.target.closest("#open-release-about");
      if (openReleaseAbout) {
        releaseOpener = openReleaseAbout;
        if (!releaseDialog.open) releaseDialog.showModal();
        void releaseController.open();
      }
      const retryReleaseAbout = event.target.closest("#retry-release-about");
      if (retryReleaseAbout) void releaseController.retry();
      const closeReleaseAbout = event.target.closest("#release-about-close, #release-about-close-secondary");
      if (closeReleaseAbout) releaseDialog.close();
      const retryPhone = event.target.closest("#phone-retry");
      if (retryPhone) void controller.startPhoneSession();
      const close = event.target.closest("[data-close-dialog]");
      if (close) close.closest("dialog").close();
      const historyDelete = event.target.closest("[data-history-delete]");
      if (historyDelete) void controller.deleteHistory(historyDelete.dataset.historyDelete);
      const historyReview = event.target.closest("[data-history-review]");
      if (historyReview) {
        const item = historyReview.closest(".history-item");
        if (item && item._record) controller.openHistory(item._record);
      }
    });

    phoneDialog.addEventListener("close", () => {
      void controller.stopPhoneSession();
    });
    phoneDialog.addEventListener("keydown", event => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      phoneDialog.close();
    });
    releaseDialog.addEventListener("click", event => {
      if (event.target === releaseDialog) releaseDialog.close();
    });
    releaseDialog.addEventListener("keydown", event => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      releaseDialog.close();
    });
    releaseDialog.addEventListener("close", () => {
      releaseController.close();
      if (releaseOpener) releaseOpener.focus();
    });

    document.getElementById("analyze-another").addEventListener("click", () => controller.reset());
    document.getElementById("try-again").addEventListener("click", () => controller.reset());
    document.getElementById("open-assessment").addEventListener("click", () => void controller.openAssessment());
    document.getElementById("retry-assessment").addEventListener("click", () => void controller.openAssessment());
    const assessmentForm = document.getElementById("assessment-form");
    const knownIssueNotes = document.getElementById("assessment-issue-notes");
    assessmentForm.addEventListener("submit", event => {
      event.preventDefault();
      validateKnownIssueNotesControl(knownIssueNotes);
      if (assessmentForm.reportValidity()) void controller.saveAssessment(assessmentForm);
    });
    assessmentForm.addEventListener("change", event => {
      if (event.target.id === "assessment-category") {
        void controller.changeAssessmentCategory(event.target.value);
      } else {
        controller.markAssessmentEditing();
      }
    });
    assessmentForm.addEventListener("input", event => {
      if (event.target.id === "assessment-issue-notes") {
        validateKnownIssueNotesControl(event.target);
      }
      if (event.target.id !== "assessment-category") controller.markAssessmentEditing();
    });
    document.getElementById("clear-history").addEventListener("click", () => {
      if (confirmClearHistory(message => global.confirm(message))) {
        void controller.clearHistory();
      }
    });

    void controller.loadHistory();
    return controller;
  }

  const exported = {
    assessmentPayloadFromValues,
    bootstrap,
    buildAssessmentPresentation,
    confirmClearHistory,
    createController,
    createReleaseAboutController,
    createDomView,
    formatCategory,
    historyPresentation,
    isSupportedImage,
    validateKnownIssueNotesControl
  };
  if (typeof module !== "undefined" && module.exports) module.exports = exported;
  global.EWasteTriage = exported;
  if (global.document) {
    if (global.document.readyState === "loading") {
      global.document.addEventListener("DOMContentLoaded", () => bootstrap(global.document), {once: true});
    } else {
      bootstrap(global.document);
    }
  }
})(typeof window !== "undefined" ? window : globalThis);
