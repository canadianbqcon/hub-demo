"""Server-side JSX transpile, so the browser stops shipping a compiler.

Every Hub React page used to pull @babel/standalone (3 MB, 636 KB gzipped) and
transpile its JSX in the browser on every load — about 900 ms of the home page's
1.6 s first paint, repeated for every visitor on every visit. The same transform
runs here instead, once per file edit, and the browser gets plain JS.

The transform is done by the SAME vendored babel build the browser was using
(static/vendor/babel.min.js is UMD, so node can require() it), which is what keeps
this from being a rewrite: identical compiler, identical preset, identical output.

No build step. Nothing to run before an edit shows up — the cache is keyed on the
file's mtime, so saving a .jsx invalidates it and the next request recompiles. That
is the whole point of the hub's edit-and-refresh model; see
wiki/problems/vesper-template-cache-stale-html for the scar from breaking it.

ponytail: an in-memory dict, no disk cache and no eviction — there are 20 files and
a process restart costs one recompile each. Move it to disk if restarts start hurting.
"""
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HUB = Path(__file__).resolve().parent
BABEL = HUB / "static" / "vendor" / "babel.min.js"

# These are the EXACT options @babel/standalone applied to a `type="text/babel"` script
# tag (presets ["react", "env"], those three plugins), and copying them is load-bearing,
# not cosmetic. It ran each file through a real <script> element, so every top-level name
# shares one global scope — the only reason a `const {useState} = React;` at the top of
# ten different files does not throw "already declared" is that preset-env with no targets
# downlevels ES5 and turns all ten into `var`. Drop preset-env for smaller modern output
# and the home page dies on the second file. preset-react stays on the classic runtime for
# the same reason the CDN tag was pinned to babel 7.x: the automatic runtime emits
# `import "react/jsx-runtime"`, an import statement in a classic script, which is a blank page.
_NODE = """
const babel = require(process.argv[1]);
const src = require('fs').readFileSync(process.argv[2], 'utf8');
process.stdout.write(babel.transform(src, {
  presets: [['react', {runtime: 'classic'}], 'env'],
  plugins: ['transform-class-properties', 'transform-object-rest-spread',
            'transform-flow-strip-types'],
  filename: process.argv[2],
  compact: false,
}).code);
"""

_cache: dict[Path, tuple[float, str]] = {}


def transpile(path: Path) -> str:
    """JSX in, plain JS out. Cached until the source file's mtime moves."""
    path = path.resolve()
    mtime = path.stat().st_mtime
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    out = subprocess.run(
        [shutil.which("node") or "node", "-e", _NODE, str(BABEL), str(path)],
        capture_output=True, text=True, timeout=120, check=True,
    ).stdout
    _cache[path] = (mtime, out)
    return out


def warm() -> None:
    """Compile every .jsx in the background at boot.

    A cold cache costs the first visitor after a restart one node spawn per script —
    on the home page that is ten of them, and it showed up as an extra 1.5 s of first
    paint. Doing it off-thread at startup makes that the server's problem instead.
    """
    def _run():
        files = [f for f in HUB.rglob("*.jsx") if "node_modules" not in f.parts]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda f: transpile(f), files))
    threading.Thread(target=_run, daemon=True).start()


if __name__ == "__main__":
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".jsx", delete=False) as f:
        f.write("const A = () => <div className='x'>hi</div>;\n")
        tmp = Path(f.name)
    js = transpile(tmp)
    assert "React.createElement" in js, js
    assert "<div" not in js, js
    assert transpile(tmp) is _cache[tmp.resolve()][1]     # second call is the cache
    tmp.write_text("const A = () => <span>bye</span>;\n")
    assert "span" in transpile(tmp)                       # mtime moved -> recompiled
    # every top-level binding must come out as `var`: these files all share one global
    # scope, so a `const` that survives collides with the identical line in the next file
    tmp.write_text("const {useState} = React;\nclass Z {}\nlet q = 1;\n")
    out = transpile(tmp)
    assert "const " not in out and "let " not in out and "class Z" not in out, out
    tmp.unlink()
    print("jsx_build self-check ok")
