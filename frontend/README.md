# SecureSign frontend

The Vue 3 single-page app behind every screen: sign-in, enrolment, verification,
customer registry, history, and the internal engineering and accounts panels. Built
with Vite, styled with Tailwind 4, routed with vue-router. No state library: `auth.js`
holds the one piece of shared state the app has.

In production nginx serves the built files and proxies `/api` to the backend, so the
app only ever talks to relative `/api/...` paths. See the repository README and
ARCHITECTURE.md for the system around it.

## Commands

    npm install
    npm run dev       # Vite dev server
    npm run check     # consistency gates, no browser needed
    npm run build     # runs the gates, then builds to dist/

`build` refuses to produce an image that would strand a user: `routing.check.mjs`
verifies every role has a landing page and every route a guard, and
`enrolStorage.check.mjs` verifies the enrolment wizard saves and restores the same
fields. The Docker build runs the same command, so a broken rule fails the image.

## Layout

    src/
      views/            one file per screen, route-level
      components/       AppShell (navigation), BrandMark, CaptureGuide,
                        IssuedPassword, NoticeBanner
      router.js         routes + guards
      accessRules.js    which role sees which screen, plain data so the check can read it
      auth.js           session state, mirrors the server's implied roles
      api.js            the one HTTP client: error envelope, 401 clears the session
      capture.js        photo quality assessment + browser-side downscale before upload
      enrolStorage.js   keeps the enrolment wizard alive across a refresh
      format.js         shared formatters: dates, distances, confidence, notice styles
      style.css         design tokens (OKLCH, sampled from the brand mark) + global rules

## Conventions

- The verdict band (valid, fraud, borderline) arrives from the server and is never
  recomputed here. The client renders decisions, it does not make them.
- Photographs are downscaled in the browser (`capture.js`) before upload. The model
  reads 224x224 after the server transform, so the discarded pixels bought nothing
  but upload time and server CPU.
- Roles come from `accessRules.js` as plain data. Add a screen there first, and the
  build gate tells you what you forgot.
- Uploads accept the file picker, the camera, and drag and drop, and all three land
  in the same handler per screen.
