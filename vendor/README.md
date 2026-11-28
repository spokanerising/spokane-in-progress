# Outside code, hosted with the site

Copies of libraries the site uses, so it doesn't depend on someone else's
server being up. Each library sits in a folder named for its version. A file
here never changes under the same address, so browsers can keep it for a
year (see `_headers`). To upgrade, add a new folder and point the pages at it.
Don't edit the old one.

| Folder | What | From |
| --- | --- | --- |
| `maplibre-gl-4.7.1/` | MapLibre GL JS, the map (`maplibre-gl.js`, `maplibre-gl.css`, `LICENSE.txt`) | npm `maplibre-gl@4.7.1`, unchanged. Package integrity `sha512-lgL7XpIwsgICiL82ITplfS7IGwrB1OJIw/pCvprDp2dhmSSEBgmPzYRvwYYYvJGJD7fxUv1Tvpih4nZ6VrLuaA==` matches the npm registry's. |
| `fonts-5.3.0/` | The two typefaces, Literata and Libre Franklin, as variable fonts (latin and latin-ext files only) plus `fonts.css` and their licenses (SIL Open Font License) | npm `@fontsource-variable/literata@5.3.0` and `@fontsource-variable/libre-franklin@5.3.0`, files unchanged. Integrity `sha512-1Jw7xvOcoGyB83lxB2nG4bfNbqtX2/TTbdh9sHAOmU064SvmSdulDtA5RBu5JYWf64fdaKX7xU+z3GO1T2bCHA==` and `sha512-PEQemCKVRtkLZJNpfvR4wG7x87c8iG05XJuEaX59ogMcAQpdtCZz/NXZUrXLJyvyx3/HD70W4LUppWLBdEdU2g==` match the registry's. `fonts.css` was written for the site; `brand/brand.json` (fonts.webfonts, fonts.preload) points the pages at it. |

The source map (`maplibre-gl.js.map`) is left out. Browsers only ask for it
when someone opens the developer tools.
