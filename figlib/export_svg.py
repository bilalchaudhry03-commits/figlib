#!/usr/bin/env python3
"""Render an HTML figure to a standalone SVG that opens correctly in Illustrator and PowerPoint.

    python -m figlib.export_svg input.html output.svg [--group] [--slide WxH] [--size WxH] [--no-size]

Runs the page in headless Chromium, then bakes computed styles (CSS-variable colours, fonts,
fill/stroke `none`, stroke geometry, opacity) into attributes, gives the SVG an intrinsic
size, converts <marker> arrowheads to plain paths, fixes XML-invalid comments, and checks the
result parses before writing it. Every output carries a <metadata> stamp with this version.
"""
import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET

from playwright.sync_api import sync_playwright

import figlib
from figlib import fonts as _fonts

__version__ = "1.3.0"

DEFAULT_SLIDE = (13.333, 7.5)   # PowerPoint 16:9 widescreen, inches

RESOLVE_JS = """
(opts) => {
  const svg = document.querySelector('svg');
  if (!svg) throw new Error('No <svg> element found in page');

  // Illustrator's SVG parser doesn't resolve var(), so colours are baked to literals.
  const presentationAttrs = ['fill', 'stroke', 'stop-color'];

  // Elements that actually paint. Restricted on purpose: blanket-inlining fill
  // onto <g>/<svg> would push an inherited black onto anything below it.
  const PAINTS = new Set(['text', 'tspan', 'rect', 'circle', 'ellipse',
                          'path', 'line', 'polyline', 'polygon', 'stop']);

  // --- geometry / opacity -------------------------------------------------
  // The page's <style> doesn't travel with outerHTML, so anything a class rule or
  // inline style set is lost unless it becomes an attribute. Bake a property iff
  // its computed value differs from what the standalone file would give the
  // element anyway: the value inherited from ancestors' attributes (tracked in
  // `inh`), or the initial value for non-inherited `opacity`.
  const INITIAL = {'fill': 'rgb(0, 0, 0)', 'stroke': 'none',
                   'stroke-width': '1', 'stroke-dasharray': 'none',
                   'stroke-dashoffset': '0', 'stroke-linecap': 'butt',
                   'stroke-linejoin': 'miter', 'fill-opacity': '1',
                   'stroke-opacity': '1'};                 // all inherited
  const GEOM = ['stroke-width', 'stroke-dasharray', 'stroke-dashoffset',
                'stroke-linecap', 'stroke-linejoin', 'fill-opacity',
                'stroke-opacity'];
  // opacity doesn't inherit (on a <g> it's group compositing), so it's safe to
  // bake on groups too.
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
  // A presentation attribute loses to any CSS rule in the browser. Probe: if
  // changing the attribute doesn't change the computed value, CSS is in control
  // and the computed value must be baked.
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
        // Paint came from a CSS rule, which doesn't travel with outerHTML;
        // without this the element imports black.
        const resolved = (computed.getPropertyValue(attr) || '').trim();
        if (resolved && resolved !== 'none') el.setAttribute(attr, resolved);
        // `none` is a value, not an absence: fill's initial value is black.
        else if (resolved === 'none' && attr !== 'stop-color' && inh[attr] !== 'none')
          el.setAttribute(attr, 'none');
      } else if (raw && paints && !inDefs && attr !== 'stop-color' && raw.trim() !== 'none') {
        // An authored colour that a class rule turns into `none` becomes none.
        // One that a class rule merely recolours is deliberately kept: the
        // authored attribute is treated as the intended colour. (Geometry below
        // follows CSS.)
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

  // --- XML comments may not contain `--` ----------------------------------
  // Collapse runs of hyphens rather than dropping the comment.
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
  // Illustrator and PowerPoint are SVG 1.1: orient="auto-start-reverse" (SVG 2)
  // falls back to no rotation, and markerUnits is widely ignored, so heads come
  // out unrotated and mis-sized. Replace each marker with an explicitly placed
  // copy, using getPointAtLength so curved paths work too.
  let markersBaked = 0, markersSkipped = 0;
  const SVGNS = 'http://www.w3.org/2000/svg';
  // Read the COMPUTED marker properties of geometry elements: marker-* inherits,
  // so a marker-end set once on a <g> must still be found on each child.
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
      // The computed form is url("#id") with quotes, the attribute form without.
      const id = (ref.match(/url\\(\\s*["']?#([^"'()\\s]+)["']?\\s*\\)/) || [])[1];
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
      // Without a viewBox, markerWidth/Height only size the clip viewport; the
      // content is used at its natural scale. Only a viewBox maps it to them.
      let sx, sy;
      if (mk.hasAttribute('viewBox')) {
        const vb = mk.getAttribute('viewBox').trim().split(/[\\s,]+/).map(Number);
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
      // Insert after the stroked element so the head paints over the line.
      el.parentNode.insertBefore(g, el.nextSibling);
      markersBaked++;
    }
  }
  // Remove the marker plumbing, or a consumer would draw each head twice.
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
  // A flat pile of 100+ siblings opens in Illustrator as 100+ top-level objects.
  // Group by proximity among contiguous siblings only (reordering would change
  // paint order). Proximity is a heuristic, hence opt-in.
  let clusters = 0;
  if (opts.group) {
    const boxOf = (el) => { try { const b = el.getBBox();
        return (b.width || b.height) ? b : null; } catch (e) { return null; } };
    const vb = svg.viewBox.baseVal;
    const gap = 0.035 * Math.hypot(vb.width || 1000, vb.height || 1000);
    // querySelectorAll excludes the root <svg>, which is where the pile usually is.
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
        // Chain off the previous element, not the running union: the union soon
        // spans the figure and swallows everything into one cluster.
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


def parse_wh(value):
    """argparse type for WxH in inches, e.g. 13.333x7.5."""
    m = re.fullmatch(r"\s*([0-9.]+)\s*[xX*]\s*([0-9.]+)\s*", value or "")
    if not m:
        raise argparse.ArgumentTypeError("expects WxH in inches, e.g. 13.333x7.5")
    return float(m.group(1)), float(m.group(2))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m figlib.export_svg",
                                 description=__doc__.strip().splitlines()[0])
    ap.add_argument("input", help="HTML figure")
    ap.add_argument("output", help="SVG to write")
    ap.add_argument("--slide", type=parse_wh, default=DEFAULT_SLIDE, metavar="WxH",
                    help="slide size in inches to fit the output to (default 13.333x7.5)")
    ap.add_argument("--size", type=parse_wh, metavar="WxH",
                    help="force this exact output size in inches")
    ap.add_argument("--no-size", action="store_true", help="don't emit width/height")
    # Opt-in: proximity grouping is a heuristic and occasionally brackets two things that are
    # merely adjacent. Worth it on a figure that exports as a flat pile, not on every figure.
    ap.add_argument("--group", action="store_true",
                    help="cluster loose neighbouring elements into <g>")
    args = ap.parse_args(argv)
    slide, force, emit_size, group = args.slide, args.size, not args.no_size, args.group
    src, dst = os.path.abspath(args.input), args.output
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
        _fonts.use_in_browser(page)   # Carlito as 'Calibri', before the figure's script runs
        page.goto(f"file://{src}")
        page.wait_for_load_state("networkidle")
        result = page.evaluate(RESOLVE_JS, opts)
        browser.close()

    # Provenance stamp. <metadata> rather than a comment: it survives Illustrator,
    # and a comment can't safely hold arbitrary text.
    stamp = (f'<metadata id="figlib-provenance">figlib.export_svg {__version__}; '
             f'figlib {figlib.build_id()}; source={os.path.basename(src)}</metadata>')
    markup = re.sub(r'(<svg\b[^>]*>)', lambda m: m.group(1) + stamp,
                    result["markup"], count=1)
    doc = '<?xml version="1.0" encoding="UTF-8"?>\n' + markup + "\n"

    # Parse before writing: Illustrator and PowerPoint reject malformed XML outright.
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
