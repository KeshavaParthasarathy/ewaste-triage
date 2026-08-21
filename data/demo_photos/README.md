# Fair-day fallback photos

Shoot 10-15 photos here before the fair, covering every class, using the same protocol
as training (scale reference in frame, varied backgrounds).

If the hotspot fails, the phone misbehaves, or the model file is corrupt, these replay
through the real /classify endpoint from the laptop alone:

    .venv/bin/python -m server.app --demo          # list them
    curl -F image=@data/demo_photos/01.jpg http://localhost:8777/classify

Last resort: a screen recording of a working session. Make one the week before.
