# Outside code, hosted with the site

Copies of libraries the site uses, so it doesn't depend on someone else's
server being up. Each library sits in a folder named for its version. A file
here never changes under the same address, so browsers can keep it for a
year (see `_headers`). To upgrade, add a new folder and point the pages at it.
Don't edit the old one.

| Folder | What | From |
| --- | --- | --- |
| `maplibre-gl-4.7.1/` | MapLibre GL JS, the map (`maplibre-gl.js`, `maplibre-gl.css`, `LICENSE.txt`) | npm `maplibre-gl@4.7.1`, unchanged. Package integrity `sha512-lgL7XpIwsgICiL82ITplfS7IGwrB1OJIw/pCvprDp2dhmSSEBgmPzYRvwYYYvJGJD7fxUv1Tvpih4nZ6VrLuaA==` matches the npm registry's. |

The source map (`maplibre-gl.js.map`) is left out. Browsers only ask for it
when someone opens the developer tools.
