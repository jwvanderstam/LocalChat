# Vendored third-party scripts

Served from this origin so the Content-Security-Policy's `script-src` names no CDN
(audit S6). Each file is the unmodified `dist` build from the npm package tarball,
whose `sha512` integrity was checked against the registry before it was copied.

| File | Package | Tarball integrity | Licence |
|---|---|---|---|
| `chart-4.5.1.umd.min.js` | `chart.js@4.5.1` | `sha512-GIjfiT9dbmHRiYi6Nl2yFCq7kkwdkp1W/lp2J99rX0yo9tgJGn3lKQATztIjb5tVtevcBtIdICNWqlq5+E8/Pw==` | MIT, `LICENSE-chart.js.md` |
| `mermaid-11.17.2.min.js` | `mermaid@11.17.2` | `sha512-V6K3C8EBdEsPFZXSKMJe6ppQOENxuHARr9GvHX4hh47lAbhMRD9qf4oEK7LoaRQxULMa80/qt5gHO73aCleBBg==` | MIT, `LICENSE-mermaid.txt` |

To upgrade: fetch the new tarball from the npm registry, check its integrity, copy
the same `dist` file under a name carrying the new version, and change the one
template that loads it. A file name that carries its version is how a reader of a
template can tell what runs.
