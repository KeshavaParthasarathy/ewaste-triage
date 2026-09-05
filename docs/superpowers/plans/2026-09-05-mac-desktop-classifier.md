# Mac Desktop Classifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a double-clickable Mac desktop classifier with a portable ONNX inference boundary, consistent image handling, private local history, model explanations, and a polished animated scan interface.

**Architecture:** Keep Flask as the application service, run it on an ephemeral loopback port, and display its bundled HTML/CSS/JavaScript through a `pywebview` native window. Training stays in PyTorch; an approved checkpoint is exported to a checksummed model bundle and loaded through an `InferenceEngine` interface using ONNX Runtime.

**Tech Stack:** Python 3.11, Flask 3.1.3, Pillow 12.3.0, pillow-heif 1.6.0, PyTorch 2.13.0, ONNX 1.22.0, ONNX Runtime 1.29.0, pywebview 6.2.1, SQLite, vanilla HTML/CSS/JavaScript, pytest 9.1.1

**Spec:** `docs/superpowers/specs/2026-09-05-ewaste-triage-mac-app-design.md`

## Global Constraints

- Initial target is Apple Silicon on macOS 14 or later.
- The normal app workflow must never require Terminal.
- Classification and history must work without internet access.
- The user app must not contain training data, training controls, or experimental checkpoints.
- Released model artifacts must be checksummed and parity-tested before packaging.
- Training, evaluation, CLI, desktop, and phone paths must share EXIF-aware normalization.
- Animation must be functional, transform/opacity based, and disabled by `prefers-reduced-motion`.
- Existing collection, CLI, valuation, and server tests must remain supported.
- Preserve unrelated uncommitted work and never overwrite `models/best.pt` during tests.

## File structure

| File | Responsibility |
|---|---|
| `server/imaging.py` | HEIF registration, EXIF normalization, RGB conversion, size validation, and model tensor creation |
| `server/model_bundle.py` | Parse and verify versioned model manifests and artifact hashes |
| `server/inference.py` | `InferenceEngine` protocol and ONNX Runtime implementation |
| `server/classifier.py` | Backward-compatible PyTorch implementation using shared preprocessing |
| `server/explanations.py` | Model-agnostic occlusion influence maps |
| `server/history.py` | Local SQLite scan history and managed thumbnails |
| `server/app.py` | Versioned desktop API and dependency injection |
| `scripts/export_onnx.py` | Approved checkpoint to ONNX bundle export and parity verification |
| `desktop/server_thread.py` | Loopback WSGI lifecycle with an ephemeral port |
| `desktop/paths.py` | Development and packaged resource/data/log path resolution |
| `desktop/main.py` | Native app bootstrap and clean shutdown |
| `server/static/index.html` | Desktop application semantic structure |
| `server/static/app.css` | Responsive visual system and motion tokens |
| `server/static/app.js` | Import, API state machine, animated results, and history behavior |
| `tests/test_imaging.py` | Image-format, size, and EXIF regressions |
| `tests/test_model_bundle.py` | Manifest and checksum validation |
| `tests/test_onnx_inference.py` | Export/inference parity and prediction schema |
| `tests/test_explanations.py` | Influence map behavior and failure isolation |
| `tests/test_history.py` | Persistence, deletion, and managed-file cleanup |
| `tests/test_desktop_api.py` | API contracts and injected service behavior |
| `tests/test_desktop_runtime.py` | Ephemeral server and GUI bootstrap behavior |
| `tests/test_desktop_ui.py` | Static UI, accessibility, motion, and no-CDN checks |

---

### Task 1: Shared image normalization

**Files:**
- Create: `server/imaging.py`
- Modify: `server/classifier.py`
- Modify: `scripts/predict.py`
- Modify: `requirements.txt`
- Test: `tests/test_imaging.py`
- Test: `tests/test_classifier.py`

**Interfaces:**
- Produces: `register_image_formats() -> None`
- Produces: `normalize_image(image: PIL.Image.Image, *, max_pixels: int = 40_000_000) -> PIL.Image.Image`
- Produces: `preprocess_array(image: PIL.Image.Image) -> numpy.ndarray` with shape `(1, 3, 224, 224)` and dtype `float32`
- Consumes: ImageNet `MEAN` and `STD`, resize-short-edge 256, center crop 224

- [ ] **Step 1: Write failing normalization tests**

```python
def test_normalize_applies_exif_orientation():
    image = Image.new("RGB", (40, 20), "red")
    image.getexif()[274] = 6
    normalized = normalize_image(image)
    assert normalized.size == (20, 40)
    assert normalized.mode == "RGB"

def test_preprocess_array_has_release_shape_and_dtype():
    value = preprocess_array(Image.new("RGB", (400, 300), "blue"))
    assert value.shape == (1, 3, 224, 224)
    assert value.dtype == np.float32
```

- [ ] **Step 2: Run the tests and confirm the orientation test fails**

Run: `.venv/bin/pytest tests/test_imaging.py tests/test_training_exif_orientation.py -v`

Expected: FAIL because `server.imaging` does not exist.

- [ ] **Step 3: Implement the shared normalization path**

```python
def normalize_image(image, *, max_pixels=40_000_000):
    if image.width * image.height > max_pixels:
        raise ImageTooLarge(f"image exceeds {max_pixels:,} pixels")
    return ImageOps.exif_transpose(image).convert("RGB")

def preprocess_array(image):
    tensor = RELEASE_TRANSFORM(normalize_image(image)).unsqueeze(0)
    return tensor.numpy().astype(np.float32, copy=False)
```

Call `pillow_heif.register_heif_opener()` exactly once from `register_image_formats()`. Refactor `Classifier.classify()` and `scripts/predict.py` to use `normalize_image` and the same release transform rather than independent pipelines.

- [ ] **Step 4: Run focused and existing classifier tests**

Run: `.venv/bin/pytest tests/test_imaging.py tests/test_classifier.py tests/test_training_exif_orientation.py tests/test_server.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the normalization boundary**

```bash
git add requirements.txt server/imaging.py server/classifier.py scripts/predict.py tests/test_imaging.py tests/test_classifier.py
git commit -m "feat: unify release image preprocessing"
```

### Task 2: Checksummed model bundle

**Files:**
- Create: `server/model_bundle.py`
- Test: `tests/test_model_bundle.py`

**Interfaces:**
- Produces: immutable `ModelManifest` dataclass with `model_id`, `architecture`, `classes`, `preprocessing_version`, `confidence_floor`, `artifact_sha256`, `schema_version`, and `metrics`
- Produces: `load_model_bundle(bundle_dir: pathlib.Path) -> tuple[ModelManifest, pathlib.Path]`
- Raises: `ModelBundleError` for missing, malformed, incompatible, or hash-mismatched bundles

- [ ] **Step 1: Write failing manifest and tamper tests**

```python
def test_load_model_bundle_verifies_sha256(tmp_path):
    model = tmp_path / "model.onnx"
    model.write_bytes(b"known model")
    write_manifest(tmp_path, artifact_sha256=hashlib.sha256(model.read_bytes()).hexdigest())
    manifest, path = load_model_bundle(tmp_path)
    assert manifest.classes == ("0301_computer_mouse", "0306_mobile_phone")
    assert path == model

def test_load_model_bundle_rejects_tampered_artifact(tmp_path):
    write_valid_bundle(tmp_path)
    (tmp_path / "model.onnx").write_bytes(b"tampered")
    with pytest.raises(ModelBundleError, match="checksum"):
        load_model_bundle(tmp_path)
```

- [ ] **Step 2: Run tests and verify the missing module failure**

Run: `.venv/bin/pytest tests/test_model_bundle.py -v`

Expected: FAIL because `server.model_bundle` does not exist.

- [ ] **Step 3: Implement strict parsing and hash verification**

```python
SUPPORTED_SCHEMA = 1

def load_model_bundle(bundle_dir):
    raw = json.loads((bundle_dir / "manifest.json").read_text())
    manifest = ModelManifest.from_mapping(raw)
    if manifest.schema_version != SUPPORTED_SCHEMA:
        raise ModelBundleError("unsupported model manifest schema")
    artifact = (bundle_dir / "model.onnx").resolve()
    if artifact.parent != bundle_dir.resolve():
        raise ModelBundleError("model artifact escapes bundle")
    if sha256_file(artifact) != manifest.artifact_sha256:
        raise ModelBundleError("model artifact checksum mismatch")
    return manifest, artifact
```

Reject duplicate classes, confidence thresholds outside `[0, 1]`, non-object metrics, absolute artifact paths, and unknown required fields.

- [ ] **Step 4: Run model-bundle tests**

Run: `.venv/bin/pytest tests/test_model_bundle.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the bundle contract**

```bash
git add server/model_bundle.py tests/test_model_bundle.py
git commit -m "feat: validate versioned model bundles"
```

### Task 3: ONNX export, parity gate, and inference engine

**Files:**
- Create: `server/inference.py`
- Create: `scripts/export_onnx.py`
- Modify: `server/classifier.py`
- Test: `tests/test_onnx_inference.py`

**Interfaces:**
- Produces: `InferenceEngine.classify(image: PIL.Image.Image) -> dict`
- Produces: `InferenceEngine.probabilities(image: PIL.Image.Image) -> numpy.ndarray`
- Produces: `OnnxClassifier(bundle_dir: pathlib.Path)`
- Produces: `export_checkpoint(checkpoint: pathlib.Path, output_dir: pathlib.Path, reference_images: Sequence[pathlib.Path], *, model_id: str) -> pathlib.Path`
- Consumes: `load_model_bundle()` and `preprocess_array()`

- [ ] **Step 1: Write failing ONNX parity and prediction-schema tests**

```python
def test_exported_onnx_matches_pytorch_top1(tiny_checkpoint, reference_images, tmp_path):
    bundle = export_checkpoint(tiny_checkpoint, tmp_path / "bundle", reference_images,
                               model_id="test-model")
    torch_engine = Classifier(tiny_checkpoint)
    onnx_engine = OnnxClassifier(bundle)
    for path in reference_images:
        torch_result = torch_engine.classify(Image.open(path))
        onnx_result = onnx_engine.classify(Image.open(path))
        assert onnx_result["class_name"] == torch_result["class_name"]
        assert onnx_result["confidence"] == pytest.approx(torch_result["confidence"], abs=1e-4)
```

- [ ] **Step 2: Run the parity test and confirm it fails before the exporter exists**

Run: `.venv/bin/pytest tests/test_onnx_inference.py -v`

Expected: FAIL because the export and ONNX engine modules do not exist.

- [ ] **Step 3: Implement export and runtime**

Export logits with fixed NCHW input `(1, 3, 224, 224)`, opset 17, explicit names `image` and `logits`, and `dynamo=False`. Run both engines over every supplied reference image, require identical top-1 output and maximum absolute probability delta no greater than `1e-4`, then write `model.onnx` and `manifest.json` atomically.

```python
class OnnxClassifier:
    def probabilities(self, image):
        logits = self.session.run(["logits"], {"image": preprocess_array(image)})[0][0]
        shifted = logits - logits.max()
        values = np.exp(shifted) / np.exp(shifted).sum()
        return values.astype(np.float32, copy=False)

    def classify(self, image):
        return prediction_from_probabilities(
            self.probabilities(image), self.manifest.classes,
            self.manifest.confidence_floor,
        )
```

- [ ] **Step 4: Run parity, classifier, and server regressions**

Run: `.venv/bin/pytest tests/test_onnx_inference.py tests/test_classifier.py tests/test_server.py -v`

Expected: PASS with no production model writes.

- [ ] **Step 5: Commit the portable inference path**

```bash
git add server/inference.py server/classifier.py scripts/export_onnx.py tests/test_onnx_inference.py
git commit -m "feat: add parity-gated ONNX inference"
```

### Task 4: Private scan history and versioned desktop API

**Files:**
- Create: `server/history.py`
- Modify: `server/app.py`
- Test: `tests/test_history.py`
- Test: `tests/test_desktop_api.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Produces: `HistoryStore(database_path: Path, media_dir: Path)`
- Produces: `HistoryStore.add_scan(prediction: Mapping, thumbnail: Image, *, retain_original: bool, original: Image | None) -> str`
- Produces: `HistoryStore.list_scans() -> list[dict]`, `get_scan(scan_id: str) -> dict | None`, `delete_scan(scan_id: str) -> bool`, `clear() -> int`
- Produces API: `POST /api/v1/classify`, `GET /api/v1/history`, `GET/DELETE /api/v1/history/<scan_id>`, `DELETE /api/v1/history`
- Preserves API: existing `/classify`, `/ingest`, `/collect`, `/health`, and `/demo`

- [ ] **Step 1: Write failing persistence and API tests**

```python
def test_delete_scan_removes_managed_thumbnail(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite", tmp_path / "media")
    scan_id = store.add_scan(PREDICTION, Image.new("RGB", (50, 50)), retain_original=False,
                             original=None)
    thumb = pathlib.Path(store.get_scan(scan_id)["thumbnail_path"])
    assert thumb.exists()
    assert store.delete_scan(scan_id) is True
    assert not thumb.exists()

def test_desktop_classify_returns_scan_id(desktop_client):
    response = desktop_client.post("/api/v1/classify", data={"image": (_jpeg_bytes(), "x.jpg")})
    assert response.status_code == 200
    assert response.json["scan_id"]
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `.venv/bin/pytest tests/test_history.py tests/test_desktop_api.py -v`

Expected: FAIL because the store and `/api/v1` endpoints do not exist.

- [ ] **Step 3: Implement transactional history and injected dependencies**

Use SQLite foreign keys, WAL mode, UUID4 scan IDs, ISO-8601 UTC timestamps, and app-owned random media filenames. Write thumbnails before committing rows; on database failure remove newly written files. Resolve every deletion target beneath `media_dir` before unlinking.

```python
def create_app(..., classifier=None, history_store=None):
    app.config["CLASSIFIER"] = classifier or Classifier(ckpt_path)
    app.config["HISTORY_STORE"] = history_store
    ...
```

The versioned endpoint classifies once, writes history when enabled, and returns the stable prediction schema plus `scan_id`. The legacy endpoint delegates to the same service but preserves its existing response fields.

- [ ] **Step 4: Run history, API, and legacy server tests**

Run: `.venv/bin/pytest tests/test_history.py tests/test_desktop_api.py tests/test_server.py -v`

Expected: PASS.

- [ ] **Step 5: Commit history and APIs**

```bash
git add server/history.py server/app.py tests/test_history.py tests/test_desktop_api.py tests/test_server.py
git commit -m "feat: add private scan history API"
```

### Task 5: Model-attention explanation service

**Files:**
- Create: `server/explanations.py`
- Modify: `server/app.py`
- Test: `tests/test_explanations.py`
- Modify: `tests/test_desktop_api.py`

**Interfaces:**
- Produces: `occlusion_map(engine: InferenceEngine, image: Image, class_index: int, *, grid_size: int = 7) -> numpy.ndarray`
- Produces API: `POST /api/v1/explain/<scan_id>` returning normalized grid values and explanation copy
- Consumes: `InferenceEngine.probabilities()` and the normalized scan image available only during the active result session

- [ ] **Step 1: Write failing explanation tests with a deterministic fake engine**

```python
def test_occlusion_map_is_normalized_and_stable():
    heat = occlusion_map(BrightnessEngine(), quadrant_image(), 0, grid_size=4)
    assert heat.shape == (4, 4)
    assert heat.min() >= 0.0
    assert heat.max() <= 1.0
    assert heat[0, 0] == pytest.approx(1.0)

def test_explanation_failure_does_not_remove_prediction(client, monkeypatch):
    monkeypatch.setattr("server.app.occlusion_map", Mock(side_effect=RuntimeError("boom")))
    response = client.post("/api/v1/explain/known-scan")
    assert response.status_code == 503
    assert response.json["prediction_available"] is True
```

- [ ] **Step 2: Run and confirm the explanation module is absent**

Run: `.venv/bin/pytest tests/test_explanations.py tests/test_desktop_api.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement bounded occlusion sensitivity**

Resize a copy to the inference crop, compute the baseline class probability, cover one grid cell at a time with the ImageNet mean color, and record non-negative score drops. Normalize by the maximum positive drop; return zeros when no cell reduces the score. Limit concurrent explanation work to one job and expire active source images after five minutes.

- [ ] **Step 4: Run explanation and API tests**

Run: `.venv/bin/pytest tests/test_explanations.py tests/test_desktop_api.py -v`

Expected: PASS.

- [ ] **Step 5: Commit explainability support**

```bash
git add server/explanations.py server/app.py tests/test_explanations.py tests/test_desktop_api.py
git commit -m "feat: explain classification influence regions"
```

### Task 6: Polished responsive scan interface

**Files:**
- Modify: `server/static/index.html`
- Create: `server/static/app.css`
- Create: `server/static/app.js`
- Test: `tests/test_desktop_ui.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes: `/api/v1/classify`, `/api/v1/explain/<scan_id>`, and `/api/v1/history`
- Produces: UI state machine `empty -> decoding -> classifying -> result|review|error`
- Produces: CSS tokens `--motion-fast: 140ms`, `--motion-standard: 220ms`, `--motion-result: 300ms`

- [ ] **Step 1: Write failing semantic, offline, and motion tests**

```python
def test_desktop_page_is_accessible_and_self_contained(client):
    html = client.get("/").get_data(as_text=True)
    for text in ("Scan", "Phone capture", "History", "Analyze another photo"):
        assert text in html
    assert 'aria-live="polite"' in html
    assert "https://" not in html and "http://" not in html

def test_styles_define_reduced_motion_and_functional_states():
    css = STATIC.joinpath("app.css").read_text()
    assert "prefers-reduced-motion: reduce" in css
    assert "data-state=\"classifying\"" in css
    assert "transform: scale(0.985)" in css
```

- [ ] **Step 2: Run UI tests and confirm the current minimal page fails**

Run: `.venv/bin/pytest tests/test_desktop_ui.py tests/test_server.py::test_capture_page_has_no_external_assets -v`

Expected: FAIL on missing navigation, motion, and accessibility structure.

- [ ] **Step 3: Implement the approved UI and state machine**

Build the approved dark/light macOS-style layout with Scan, Phone capture placeholder,
and History navigation. Use native controls, visible focus, drag-and-drop, HEIC-capable
file selection, thumbnail preview, prediction, top-three alternatives, low-confidence
review, influence overlay, optional valuation, local-history deletion, and explicit
honesty copy.

```javascript
function transition(next, payload = {}) {
  document.documentElement.dataset.state = next;
  renderState(next, payload);
}

async function analyze(file) {
  transition('decoding');
  const body = new FormData();
  body.append('image', file, file.name);
  transition('classifying');
  const result = await api('/api/v1/classify', {method: 'POST', body});
  transition(result.low_confidence ? 'review' : 'result', result);
  void loadExplanation(result.scan_id);
}
```

Animate button press, option selection, drop-target lift, result entrance, confidence
bars, and history insertion using transform/opacity. Cap total staged result motion at
350 ms. Under reduced motion, remove scale, spring, stagger, and sweeping effects.

- [ ] **Step 4: Run UI and server tests**

Run: `.venv/bin/pytest tests/test_desktop_ui.py tests/test_server.py tests/test_desktop_api.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the desktop experience**

```bash
git add server/static/index.html server/static/app.css server/static/app.js tests/test_desktop_ui.py tests/test_server.py
git commit -m "feat: build polished desktop scan experience"
```

### Task 7: Native desktop bootstrap

**Files:**
- Create: `desktop/__init__.py`
- Create: `desktop/paths.py`
- Create: `desktop/server_thread.py`
- Create: `desktop/main.py`
- Create: `requirements-app.txt`
- Test: `tests/test_desktop_runtime.py`

**Interfaces:**
- Produces: `AppPaths.for_runtime(frozen: bool, executable: Path | None = None) -> AppPaths`
- Produces: `ServerThread(app, host="127.0.0.1", port=0)` with `start_and_wait() -> str` and `shutdown() -> None`
- Produces: `desktop.main.run(webview_module=webview) -> int`
- Consumes: verified model bundle path and local Application Support paths

- [ ] **Step 1: Write failing runtime lifecycle tests**

```python
def test_server_thread_uses_ephemeral_loopback_port():
    server = ServerThread(create_health_app(), port=0)
    url = server.start_and_wait()
    assert url.startswith("http://127.0.0.1:")
    assert requests.get(url + "/health", timeout=2).status_code == 200
    server.shutdown()

def test_desktop_run_opens_one_native_window(fake_webview, app_paths):
    assert run(webview_module=fake_webview, paths=app_paths) == 0
    assert fake_webview.created[0]["title"] == "E-Waste Triage"
```

- [ ] **Step 2: Run the runtime tests and verify the desktop package is absent**

Run: `.venv/bin/pytest tests/test_desktop_runtime.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement path resolution, loopback lifecycle, and GUI launch**

Use `werkzeug.serving.make_server`, signal readiness only after the bound port is known,
and place writable data under `~/Library/Application Support/E-Waste Triage/`. In a
frozen app, resolve bundled static files, model, and reference assets relative to
`sys._MEIPASS`; never write there.

```python
def run(*, webview_module=webview, paths=None):
    paths = paths or AppPaths.for_runtime(getattr(sys, "frozen", False))
    app = build_desktop_app(paths)
    server = ServerThread(app)
    url = server.start_and_wait()
    try:
        webview_module.create_window("E-Waste Triage", url, min_size=(760, 620))
        webview_module.start(debug=False)
        return 0
    finally:
        server.shutdown()
```

Pin only app-specific dependencies in `requirements-app.txt`; it includes
`pywebview==6.2.1`, `pillow-heif==1.6.0`, and the already pinned runtime dependencies.

- [ ] **Step 4: Run the first complete desktop-plan test set**

Run: `.venv/bin/pytest tests/test_imaging.py tests/test_model_bundle.py tests/test_onnx_inference.py tests/test_explanations.py tests/test_history.py tests/test_desktop_api.py tests/test_desktop_ui.py tests/test_desktop_runtime.py tests/test_server.py tests/test_classifier.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the Mac desktop vertical slice**

```bash
git add desktop requirements-app.txt tests/test_desktop_runtime.py
git commit -m "feat: launch classifier as a Mac desktop app"
```

## Plan completion gate

The plan is complete when the development launcher opens a native window, classifies
through the ONNX bundle, renders the influence explanation without blocking the result,
persists and deletes local history safely, handles EXIF/HEIC inputs, and passes every
focused and legacy regression listed above. Packaging is completed in the third plan.

