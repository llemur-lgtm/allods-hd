# cnc-ddraw

DirectDraw replacement used for rendering.

- Project: https://github.com/FunkyFr3sh/cnc-ddraw
- Version: 7.1.0.0 (`cnc-ddraw.zip` from the official release)
- `ddraw.dll` SHA-256: `85e0f7d530dfda134793a57cb3e76b0287dcc96892ee57162dd68f47283b03a9`
- License: MIT, see [LICENSE](LICENSE)

The configuration used by the patch is [`game/ddraw.ini`](../../game/ddraw.ini): the default
`ddraw.ini` of this release with `fullscreen`, `windowed` and `maintas` set to `true`
(borderless fullscreen, aspect ratio kept) and a `[ROM_HD]` section for the patched executable.
