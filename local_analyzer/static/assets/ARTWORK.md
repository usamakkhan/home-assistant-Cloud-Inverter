# Dashboard artwork

The dashboard serves two bundled PNG illustrations from `static/assets`.
Both files are `1536 × 1024` pixels and load from the local analyzer; the
dashboard does not fetch them from a remote image service. The repository's
original asset notes record image generation on 2026-09-02.

| File | Used for | What it depicts |
| --- | --- | --- |
| `home-energy-v1.png` | Home/energy illustration | An isometric house with rooftop panels and generic energy equipment. |
| `inverter-kit-v1.png` | Device/equipment illustration | Unbranded inverter and home-battery housings. |

The artwork is conceptual. It is not a photograph of a user's home, a wiring
diagram, a measured power-flow display, or an accurate rendering of a
particular SolarMax model. Device ratings, layout, connections, and operating
status must come from actual telemetry or device documentation, not these
images.

## Design intent

Both illustrations use a dark navy background with restrained teal and warm
accents so they fit the dashboard without looking like live data. They contain
no readable device screen, serial number, address, logo, specification label,
or personal scene detail. The HTML gives the equipment image descriptive
alternative text and labels it as an illustration.

When replacing either file, keep its local path or update the dashboard's
asset mapping in `app.py` and the corresponding `<img>` reference in
`static/index.html`. Preserve the distinction between decoration and
measurement in the caption and alternative text.
