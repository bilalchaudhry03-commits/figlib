#!/usr/bin/env python3
"""Render a scientific-figure-design HTML file to a standalone SVG.

CANONICAL COPY. Moved into the repo from ~/.claude/skills/ on 2026-08-27 and
given a version, because it is a BUILD TOOL for a repo artifact and living
outside version control made its output unattributable: on 2026-08-27, 13 of 19
deck SVGs failed to reproduce from their HTML and separating "the exporter
improved" from "the figure drifted" took hours. Every SVG it writes now carries
a <metadata> stamp naming this version, so that question is answerable by
reading the file.

Run as:  python3 -m figlib.export_svg in.html out.svg


Loads the HTML in headless Chromium so any layout-computing <script> in the
page runs first, then bakes every CSS custom-property color reference
(var(--x)) on the SVG subtree down to its literal computed value -- Illustrator's
SVG parser does not resolve var() the way a browser does -- and inlines
font-family/size/weight onto text so labels survive without the page's
stylesheet. Since 1.2.0 it also bakes class/inline-set `fill:none`/`stroke:none`
and stroke geometry/opacity (see the comment above GEOM in RESOLVE_JS).

Three things this also does, each because it silently produced a broken
deliverable in practice (2026-08-04):

  * **Emits width/height when the author did not.** These figures size their
    SVG with a CSS rule (`svg{width:100%}`), which does not travel with
    outerHTML, so the export carried a viewBox and no intrinsic size. Illustrator
    copes; **PowerPoint does not** -- with no width/height it imports the graphic
    at a small default, which reads as "the figure is too small" and is not
    fixable by scaling on the slide without quality loss. The emitted size fits
    the figure to a 16:9 slide (13.333 x 7.5 in) preserving aspect, so a
    wide figure comes out slide-width and a tall one comes out slide-height.
    An author-set width/height always wins; `--no-size` opts out entirely.

  * **Sanitises XML comments.** An XML comment may not contain a double hyphen.
    HTML tolerates `<!-- ------ card 1 ------ -->`; XML does not, so such a file
    is rejected outright by Illustrator and PowerPoint at load with a parse
    error pointing at a line the author has no reason to suspect. Runs of two or
    more hyphens inside comments are collapsed to one.

  * **Parses its own output before reporting success.** The pre-existing
    var()-resolution check verifies colours survive; it cannot see a
    well-formedness problem, so a file could pass every check and still be
    unopenable. This is the guard that actually catches that class.

Usage:
    python3 export_svg.py input.html output.svg [options]

Options:
    --slide WxH   target slide size in inches for auto-sizing
                  (default 13.333x7.5, i.e. 16:9 widescreen)
    --size WxH    force this exact output size in inches, ignoring the slide fit
    --no-size     do not emit width/height at all (pre-2026-08-04 behaviour)
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

__version__ = "1.2.0"

from playwright.sync_api import sync_playwright

# Importing figlib.fonts registers the vendored Carlito with matplotlib and
# symlinks it where fontconfig will find it, so headless Chromium measures
# the face the deck actually declares instead of a fallback 20% wider.
from figlib import fonts as _fonts  # noqa: F401


DEFAULT_SLIDE = (13.333, 7.5)   # PowerPoint 16:9 widescreen, inches

RESOLVE_JS = """
(opts) => {
  const svg = document.querySelector('svg');
  if (!svg) throw new Error('No <svg> element found in page');

  const presentationAttrs = ['fill', 'stroke', 'stop-color'];

  // Elements that actually paint. Restricted on purpose: blanket-inlining fill
  // onto <g>/<svg> would push an inherited black onto anything below it.
  const PAINTS = new Set(['text', 'tspan', 'rect', 'circle', 'ellipse',
                          'path', 'line', 'polyline', 'polygon', 'stop']);

  // --- geometry / opacity properties (1.2.0, 2026-10-19) -------------------
  // Up to 1.1.0 only the COLOURS above were baked, and a computed `none` was
  // skipped as "nothing to write". Both were wrong for a standalone file: the
  // page's <style> does not travel with outerHTML, so whatever a class rule or
  // inline style set is gone unless it becomes an attribute -- and `fill` has
  // an initial value of BLACK, so a dropped `fill:none` is not "nothing", it is
  // a solid black shape (generals Fig 5A: every outline-only oocyte circle).
  // Class-set stroke-width reverted to 1 and dasharrays to solid the same way.
  //
  // Rule: bake a property iff the browser's computed value differs from what
  // the STANDALONE file would give that element without the attribute -- i.e.
  // the value inherited from ancestors' attributes in the export (tracked
  // top-down in `inh`), or the initial value for non-inherited `opacity`.
  // That writes every value that would otherwise be lost and nothing that is
  // already implied, so all-default shapes gain no attributes.
  const INITIAL = {'fill': 'rgb(0, 0, 0)', 'stroke': 'none',
                   'stroke-width': '1', 'stroke-dasharray': 'none',
                   'stroke-dashoffset': '0', 'stroke-linecap': 'butt',
                   'stroke-linejoin': 'miter', 'fill-opacity': '1',
                   'stroke-opacity': '1'};                 // all inherited
  const GEOM = ['stroke-width', 'stroke-dasharray', 'stroke-dashoffset',
                'stroke-linecap', 'stroke-linejoin', 'fill-opacity',
                'stroke-opacity'];
  // opacity does not inherit, and on a <g> it is group compositing, so unlike
  // fill it is safe -- and needed -- to bake on groups too.
  const OPACITY_ON = new Set([...PAINTS, 'g']);
  OPACITY_ON.delete('stop');

  // Computed lengths come back as "1.6px" / "4px, 3px"; write plain numbers.
  const norm = (attr, v) => {
    v = (v || '').trim();
    if (attr === 'stroke-width' || attr === 'stroke-dashoffset') return v.replace(/px$/, '');
    if (attr === 'stroke-dasharray') {
      if (v === 'none') return v;
      return v.replace(/px/g, '').split(/[\\s,]+/).filter(Boolean).join(' ');
    }
    return v;
  };
  // A value no figure uses, different from `cur`, to probe the cascade with.
  const SENTINEL = {'stroke-width': '1234.5', 'stroke-dasharray': '1234.5',
                    'stroke-dashoffset': '1234.5', 'fill-opacity': '0.123',
                    'stroke-opacity': '0.123', 'opacity': '0.123'};
  const sentinel = (attr, cur) => {
    if (attr === 'stroke-linecap') return cur === 'square' ? 'round' : 'square';
    if (attr === 'stroke-linejoin') return cur === 'bevel' ? 'round' : 'bevel';
    return SENTINEL[attr];
  };
  // An authored presentation attribute LOSES to any CSS rule in the browser,
  // so `<line stroke-width="2" class="thin">` is drawn at the class width on
  // screen and at 2 in the export. Probe: if changing the attribute does not change the
  // computed value, CSS is in control and the computed value must be baked.
  const cssOverrides = (el, attr, cur) => {
    const raw = el.getAttribute(attr);
    el.setAttribute(attr, sentinel(attr, cur));
    const probe = norm(attr, getComputedStyle(el).getPropertyValue(attr));
    el.setAttribute(attr, raw);
    return probe === cur;
  };

  const bake = (el, inh) => {
    const computed = getComputedStyle(el);
    const tag = el.tagName.toLowerCase();
    const paints = PAINTS.has(tag);
    const inDefs = !!el.closest('defs');
    for (const attr of presentationAttrs) {
      const raw = el.getAttribute(attr);
      if (raw && raw.includes('var(')) {
        // authored as an attribute referencing a custom property
        const resolved = computed.getPropertyValue(attr);
        if (resolved) el.setAttribute(attr, resolved.trim());
      } else if (!raw && paints && !inDefs &&
                 (attr !== 'stop-color' || tag === 'stop')) {
        // Paint came from a CSS rule in the page's <style>, which does NOT
        // travel with svg.outerHTML -- without this the element falls back to
        // black on import (white-on-dark labels vanish, greys flatten to black).
        const resolved = (computed.getPropertyValue(attr) || '').trim();
        if (resolved && resolved !== 'none') el.setAttribute(attr, resolved);
        // `none` is a value, not an absence: fill's initial value is black.
        else if (resolved === 'none' && attr !== 'stop-color' && inh[attr] !== 'none')
          el.setAttribute(attr, 'none');
      } else if (raw && paints && !inDefs && attr !== 'stop-color' && raw.trim() !== 'none') {
        // An authored COLOUR that a class rule turns into `none` (an outline
        // class on a shape built with a fill attribute) must become none.
        // An authored colour that a class rule merely RECOLOURS is left alone,
        // deliberately: that is pre-1.2.0 behaviour, and in the deck the
        // authored attribute is the intended colour (white numerals on a dark
        // badge that a `.tag{fill:muted}` rule greys out on screen) -- see
        // figlib/CLAUDE.md. Geometry below has no such history and follows CSS.
        const resolved = (computed.getPropertyValue(attr) || '').trim();
        if (resolved === 'none') el.setAttribute(attr, 'none');
      }
    }
    if (!inDefs) {
      const props = paints && tag !== 'stop' ? [...GEOM] : [];
      if (OPACITY_ON.has(tag)) props.push('opacity');
      for (const attr of props) {
        const raw = el.getAttribute(attr);
        const cur = norm(attr, computed.getPropertyValue(attr));
        if (!cur) continue;
        if (raw && raw.includes('var(')) { el.setAttribute(attr, cur); continue; }
        if (raw) {
          if (norm(attr, raw) !== cur && cssOverrides(el, attr, cur)) el.setAttribute(attr, cur);
          continue;
        }
        const implied = attr === 'opacity' ? '1' : inh[attr];
        if (cur !== implied) el.setAttribute(attr, cur);
      }
    }
    // What a child inherits in the STANDALONE file: this element's attributes
    // (as now baked), else whatever its own ancestors supplied.
    const next = Object.assign({}, inh);
    for (const attr of Object.keys(INITIAL)) {
      const a = el.getAttribute(attr);
      if (a && !a.includes('var(') && a !== 'inherit') {
        next[attr] = (attr === 'fill' || attr === 'stroke') ? (a.trim() === 'none' ? 'none' : a.trim())
                                                             : norm(attr, a);
      }
    }
    for (const child of el.children) bake(child, next);
  };
  bake(svg, Object.assign({}, INITIAL));

  svg.querySelectorAll('text, tspan').forEach((t) => {
    const computed = getComputedStyle(t);
    t.setAttribute('font-family', computed.fontFamily);
    t.setAttribute('font-size', computed.fontSize);
    t.setAttribute('font-weight', computed.fontWeight);
  });

  // --- XML comments may not contain a double hyphen -----------------------
  // Collapse runs of 2+ hyphens rather than dropping the comment, so authoring
  // notes survive into the deliverable.
  let commentsFixed = 0;
  const walker = document.createTreeWalker(svg, NodeFilter.SHOW_COMMENT);
  const comments = [];
  while (walker.nextNode()) comments.push(walker.currentNode);
  for (const c of comments) {
    // also guard a comment ending in '-', which would close as '--->'
    const cleaned = c.data.replace(/-{2,}/g, '-').replace(/-$/, '');
    if (cleaned !== c.data) { c.data = cleaned; commentsFixed++; }
  }


  // --- bake <marker> arrowheads into plain geometry ------------------------
  // Illustrator and PowerPoint render SVG 1.1. Two consequences, and BOTH make
  // an arrowhead come out as a bare triangle:
  //   * orient="auto-start-reverse" is SVG 2. In 1.1 it is an invalid value, so
  //     it falls back to no rotation -- every arrowhead is drawn in its authored
  //     orientation no matter which way its line runs.
  //   * markerUnits defaults to "strokeWidth" and is widely ignored, so the
  //     head also comes out the wrong size.
  // Replacing each marker with an explicit, already-positioned and already-
  // rotated path removes both failure modes: the deliverable then contains only
  // primitives every consumer supports. Geometry comes from the live DOM
  // (getPointAtLength), so curved paths are handled as exactly as straight ones.
  let markersBaked = 0, markersSkipped = 0;
  const SVGNS = 'http://www.w3.org/2000/svg';
  // Walk GEOMETRY elements and read the COMPUTED marker properties, rather than
  // scanning for the marker-* attribute. Marker properties inherit, so an author
  // may set marker-end once on a <g> and have every child arrow pick it up -- and
  // a <g> has no getTotalLength, so an attribute scan skips it and silently leaves
  // those arrowheads as markers. One figure here does exactly that.
  const markered = Array.from(svg.querySelectorAll('path,line,polyline,polygon'));
  for (const el of markered) {
    const cs0 = getComputedStyle(el);
    if (cs0.markerMid && cs0.markerMid !== 'none') { markersSkipped++; }
    const wanted = {start: cs0.markerStart, end: cs0.markerEnd};
    if ((!wanted.start || wanted.start === 'none') &&
        (!wanted.end   || wanted.end   === 'none')) continue;
    if (typeof el.getTotalLength !== 'function') { markersSkipped++; continue; }
    let total;
    try { total = el.getTotalLength(); } catch (e) { markersSkipped++; continue; }
    if (!(total > 0)) { markersSkipped++; continue; }
    const sw = parseFloat(getComputedStyle(el).strokeWidth) || 1;
    const eps = Math.min(1, total / 100);

    for (const pos of ['start', 'end']) {
      const ref = wanted[pos];
      if (!ref || ref === 'none') continue;
      el.setAttribute('marker-' + pos, 'none');   // override any inherited value
      // getComputedStyle returns url("#id") WITH quotes; the attribute form has
      // none. Strip both, or the id carries a trailing quote and querySelector
      // throws on an invalid selector.
      const id = (ref.match(/url\(\s*["']?#([^"'()\s]+)["']?\s*\)/) || [])[1];
      const mk = id && svg.querySelector('marker[id="' + id + '"]');
      if (!mk) { markersSkipped++; continue; }

      // Tangent in the direction of travel, at the relevant end.
      const at = pos === 'start' ? 0 : total;
      const near = pos === 'start' ? eps : total - eps;
      const P = el.getPointAtLength(at), Q = el.getPointAtLength(near);
      let ang = pos === 'start'
        ? Math.atan2(Q.y - P.y, Q.x - P.x)
        : Math.atan2(P.y - Q.y, P.x - Q.x);
      // auto-start-reverse flips the START marker only; plain auto does not.
      if (pos === 'start' && (mk.getAttribute('orient') || '') === 'auto-start-reverse') {
        ang += Math.PI;
      }
      const orient = mk.getAttribute('orient') || '0';
      if (orient !== 'auto' && orient !== 'auto-start-reverse') {
        ang = (parseFloat(orient) || 0) * Math.PI / 180;
      }

      const mW = parseFloat(mk.getAttribute('markerWidth')  || '3');
      const mH = parseFloat(mk.getAttribute('markerHeight') || '3');
      // markerUnits: strokeWidth (the default) scales the head by the stroke.
      const unit = (mk.getAttribute('markerUnits') || 'strokeWidth') === 'userSpaceOnUse' ? 1 : sw;
      // A marker WITHOUT a viewBox is not scaled to markerWidth/markerHeight -- those
      // only size the clip viewport, and the content is used at its natural scale.
      // Treating a missing viewBox as "0 0 10 10" applies a markerWidth/10 scale that
      // does not exist, which silently resized every arrowhead in the eight figures
      // here whose markers omit it. Only a marker that HAS a viewBox gets that mapping.
      let sx, sy;
      if (mk.hasAttribute('viewBox')) {
        const vb = mk.getAttribute('viewBox').trim().split(/[\s,]+/).map(Number);
        sx = unit * (mW / (vb[2] || 10));
        sy = unit * (mH / (vb[3] || 10));
      } else {
        sx = unit; sy = unit;
      }
      const refX = parseFloat(mk.getAttribute('refX') || '0');
      const refY = parseFloat(mk.getAttribute('refY') || '0');

      const g = document.createElementNS(SVGNS, 'g');
      g.setAttribute('transform',
        'translate(' + P.x + ',' + P.y + ') ' +
        'rotate(' + (ang * 180 / Math.PI) + ') ' +
        'scale(' + sx + ',' + sy + ') ' +
        'translate(' + (-refX) + ',' + (-refY) + ')');
      for (const child of Array.from(mk.children)) g.appendChild(child.cloneNode(true));
      // Insert AFTER the stroked element so the head paints over the line, which
      // is what the browser does and what the author saw.
      el.parentNode.insertBefore(g, el.nextSibling);
      markersBaked++;
    }
  }
  // Every arrowhead is now explicit geometry, so the marker plumbing is dead
  // weight -- and leaving a marker-* attribute behind would make a consumer draw
  // the head a second time, on top of the baked one.
  if (markersBaked && !markersSkipped) {
    for (const el of Array.from(svg.querySelectorAll(
           '[marker-start],[marker-end],[marker-mid]'))) {
      el.removeAttribute('marker-start');
      el.removeAttribute('marker-end');
      el.removeAttribute('marker-mid');
    }
    for (const mk of Array.from(svg.querySelectorAll('marker'))) mk.remove();
  }


  // --- optional: cluster loose siblings into <g> for Illustrator ----------
  // These figures build their content by appending every shape and label to one
  // container, so the export is a flat pile of 100+ siblings. Illustrator opens
  // that as 100+ top-level objects: moving "the box and its caption" means
  // rubber-band selecting them every time.
  //
  // Grouping is by PROXIMITY among CONTIGUOUS siblings only. Contiguity matters:
  // reordering would change paint order and therefore the picture. Proximity is
  // a heuristic -- it reliably catches a shape and the label sitting on it, and
  // it will occasionally group two things that are merely adjacent. That is why
  // this is opt-in rather than always-on.
  let clusters = 0;
  if (opts.group) {
    const boxOf = (el) => { try { const b = el.getBBox();
        return (b.width || b.height) ? b : null; } catch (e) { return null; } };
    const vb = svg.viewBox.baseVal;
    const gap = 0.035 * Math.hypot(vb.width || 1000, vb.height || 1000);
    // querySelectorAll searches DESCENDANTS, so the root <svg> is not in its own
    // result set -- and on these figures the flat pile of siblings lives exactly
    // there. Omitting it made this a no-op on precisely the files it is for.
    for (const parent of [svg, ...Array.from(svg.querySelectorAll('g'))]) {
      const kids = Array.from(parent.children).filter(
        k => !/^(defs|marker|clipPath|metadata|title|desc|style)$/i.test(k.tagName));
      if (kids.length < 6) continue;
      let run = [], runBox = null;
      const flush = () => {
        if (run.length >= 2) {
          const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
          g.setAttribute('class', 'cluster');
          run[0].parentNode.insertBefore(g, run[0]);
          run.forEach(el => g.appendChild(el));
          clusters++;
        }
        run = []; runBox = null;
      };
      for (const k of kids) {
        const b = boxOf(k);
        if (!b) { flush(); continue; }
        const box = {x1: b.x, y1: b.y, x2: b.x + b.width, y2: b.y + b.height};
        if (runBox === null) { run = [k]; runBox = box; continue; }
        // Chain off the PREVIOUS element, not the running union. The union grows
        // monotonically, so after a handful of elements it spans the figure and
        // every remaining one is trivially "near" it -- which produced exactly
        // one all-encompassing cluster at every threshold tried, i.e. no
        // grouping at all wearing the costume of grouping.
        const dx = Math.max(0, Math.max(runBox.x1 - box.x2, box.x1 - runBox.x2));
        const dy = Math.max(0, Math.max(runBox.y1 - box.y2, box.y1 - runBox.y2));
        if (Math.hypot(dx, dy) <= gap) { run.push(k); runBox = box; }
        else { flush(); run = [k]; runBox = box; }
      }
      flush();
    }
  }

  // --- intrinsic size ------------------------------------------------------
  // PowerPoint needs width/height; a viewBox alone gives it nothing to scale to.
  let sized = null;
  const hadSize = svg.getAttribute('width') && svg.getAttribute('height');
  if (opts.emitSize && !hadSize) {
    let w = null, h = null;
    if (opts.forceW && opts.forceH) {
      w = opts.forceW; h = opts.forceH;
    } else {
      const vb = (svg.getAttribute('viewBox') || '').trim().split(/[\\s,]+/).map(Number);
      if (vb.length === 4 && vb[2] > 0 && vb[3] > 0) {
        const scale = Math.min(opts.slideW / vb[2], opts.slideH / vb[3]);
        w = vb[2] * scale; h = vb[3] * scale;
      }
    }
    if (w && h) {
      const r = (x) => (Math.round(x * 1000) / 1000) + 'in';
      svg.setAttribute('width', r(w));
      svg.setAttribute('height', r(h));
      sized = r(w) + ' x ' + r(h);
    }
  }

  svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  if (!svg.getAttribute('xmlns:xlink')) {
    svg.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');
  }
  return {markup: svg.outerHTML, sized, hadSize: !!hadSize, commentsFixed,
          markersBaked, markersSkipped, clusters};
}
"""


def parse_wh(value, flag):
    m = re.fullmatch(r"\s*([0-9.]+)\s*[xX*]\s*([0-9.]+)\s*", value or "")
    if not m:
        sys.exit(f"error: {flag} expects WxH in inches, e.g. 13.333x7.5")
    return float(m.group(1)), float(m.group(2))


def main():
    args = sys.argv[1:]
    slide = DEFAULT_SLIDE
    force = None
    emit_size = True
    group = False

    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--no-size":
            emit_size = False
        elif a == "--group":
            # Opt-in: proximity grouping is a heuristic and will occasionally
            # bracket two things that are merely adjacent. Worth it on a figure
            # that exports as a flat pile; not worth imposing on every figure.
            group = True
        elif a == "--slide":
            i += 1
            slide = parse_wh(args[i] if i < len(args) else None, "--slide")
        elif a == "--size":
            i += 1
            force = parse_wh(args[i] if i < len(args) else None, "--size")
        elif a.startswith("-"):
            sys.exit(f"error: unknown option {a}\n\n{__doc__}")
        else:
            positional.append(a)
        i += 1

    if len(positional) != 2:
        sys.exit(f"usage: {sys.argv[0]} input.html output.svg [--slide WxH] "
                 f"[--size WxH] [--no-size]")

    src = os.path.abspath(positional[0])
    dst = positional[1]
    if not os.path.isfile(src):
        sys.exit(f"error: {src} does not exist")

    opts = {
        "emitSize": emit_size,
        "slideW": slide[0], "slideH": slide[1],
        "group": group,
        "forceW": force[0] if force else None,
        "forceH": force[1] if force else None,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{src}")
        page.wait_for_load_state("networkidle")
        result = page.evaluate(RESOLVE_JS, opts)
        browser.close()

    # Provenance stamp. <metadata> is standard SVG, ignored by renderers, and
    # survives Illustrator. Deliberately NOT an XML comment: a comment may not
    # contain a double hyphen and a version string is a bad place to find out.
    stamp = (f'<metadata id="figlib-provenance">figlib.export_svg {__version__}; '
             f'source={os.path.basename(src)}</metadata>')
    markup = re.sub(r'(<svg\b[^>]*>)', lambda m: m.group(1) + stamp,
                    result["markup"], count=1)
    doc = '<?xml version="1.0" encoding="UTF-8"?>\n' + markup + "\n"

    # Parse before writing. A file that is not well-formed XML is rejected
    # outright by Illustrator and PowerPoint, and no colour/font check can see
    # it -- this is the only guard that catches that class of defect.
    try:
        ET.fromstring(doc)
    except ET.ParseError as exc:
        sys.exit(f"error: export is not well-formed XML and would not open "
                 f"({exc}).\nNothing written. Check the HTML for comments "
                 f"containing '--', or for raw '&' / '<' in text.")

    with open(dst, "w") as f:
        f.write(doc)

    notes = []
    if result["hadSize"]:
        notes.append("kept author width/height")
    elif result["sized"]:
        notes.append(f"sized {result['sized']}")
    elif emit_size:
        notes.append("NOT sized (no usable viewBox) -- will import small")
    if result["commentsFixed"]:
        notes.append(f"sanitised {result['commentsFixed']} comment(s)")
    if result.get("markersBaked"):
        notes.append(f"baked {result['markersBaked']} arrowhead(s)")
    if result.get("clusters"):
        notes.append(f"grouped into {result['clusters']} cluster(s)")
    if result.get("markersSkipped"):
        notes.append(f"⚠ {result['markersSkipped']} marker(s) NOT baked")
    print(f"wrote {dst}" + (f"  [{', '.join(notes)}]" if notes else ""))


if __name__ == "__main__":
    main()
