# Neumorphic + Apple-Inspired Glass UI Enhancement Guide
## Addendum to the Existing Neumorphic Frontend Style Guide

This document **extends** the existing neumorphic style guide rather than replacing it.

The current interface already has the right foundation:

- warm light-gray canvas
- soft raised cards
- rounded surfaces
- low-saturation color
- restrained shadows
- clean typography
- simple iconography

The next step is to add a **glass/material layer inspired by modern Apple interface design** so the product feels more dimensional, polished, and alive instead of uniformly matte and flat.

The target is **not** "make every card glass."  
The target is:

> **Neumorphic content surfaces + translucent floating controls + subtle layered depth + soft optical highlights.**

Think of the page as having three physical layers:

```text
1. Background plane
2. Soft neumorphic content surfaces
3. Floating glass controls / navigation / temporary interactive surfaces
```

This layered system is the core visual direction for the frontend.

---

# 1. Design Goal

The finished interface should feel like a hybrid of:

```text
soft industrial dashboard
+
premium Apple-like translucent controls
+
subtle depth and optical layering
```

It should feel:

```text
soft
dimensional
tactile
translucent
calm
precise
premium
modern
adaptive
slightly luminous
```

It should **not** feel:

```text
generic glassmorphism
frosted everywhere
neon
cyberpunk
overly glossy
high-contrast
busy
plastic
flat
opaque
```

The current neumorphic design remains the content language.

Glass is used to create hierarchy and interactivity.

---

# 2. Core Principle: Glass Is a Functional Layer

Do not convert every card into glass.

Use glass mainly for elements that visually sit **above** the content layer:

- top navigation
- floating toolbar
- floating status badges
- segmented controls
- action buttons
- coach prompt controls
- popovers
- tooltips
- menus
- overlays
- filter controls
- floating bottom bars
- sticky controls
- modal surfaces
- temporary interaction surfaces

Keep primary content containers such as:

- Physiology
- Weekly plan
- Tasks
- Wearable timeline
- Charts
- Main dashboard sections

as **soft neumorphic / standard material surfaces**.

This creates obvious depth:

```text
glass = controls / navigation / interaction
neumorphism = data / content / structure
```

Apple's current Human Interface Guidelines make a similar distinction: Liquid Glass is best used as a functional layer for controls and navigation, while standard materials remain appropriate for content surfaces.

---

# 3. Visual Layer Stack

Use this conceptual hierarchy.

## Layer 0 — Ambient background

The global gray canvas.

```css
--bg-base: #d7d8d7;
```

Optional subtle environmental tint:

```css
body {
  background:
    radial-gradient(
      circle at 20% 0%,
      rgba(255,255,255,.26),
      transparent 30%
    ),
    radial-gradient(
      circle at 95% 15%,
      rgba(174,193,198,.11),
      transparent 28%
    ),
    #d7d8d7;
}
```

The gradients must remain extremely subtle.

They exist so translucent glass has something to interact with.

---

## Layer 1 — Neumorphic content surfaces

Used for data-rich sections.

```css
--surface-neu: rgba(220, 221, 220, .96);
```

```css
.neu-panel {
  background: var(--surface-neu);
  border-radius: 30px;

  box-shadow:
    -10px -10px 24px rgba(255,255,255,.52),
     10px  10px 24px rgba(137,140,140,.25);
}
```

These remain mostly opaque.

---

## Layer 2 — Glass controls

Used for floating or interactive UI.

```css
--glass-bg: rgba(244, 246, 246, .42);
--glass-bg-strong: rgba(244, 246, 246, .60);
--glass-border: rgba(255,255,255,.48);
```

```css
.glass {
  background: rgba(244,246,246,.42);

  border: 1px solid rgba(255,255,255,.46);

  backdrop-filter:
    blur(18px)
    saturate(125%);

  -webkit-backdrop-filter:
    blur(18px)
    saturate(125%);
}
```

---

## Layer 3 — Floating glass

For major navigation and temporary overlays.

```css
.glass-floating {
  background:
    linear-gradient(
      135deg,
      rgba(255,255,255,.55),
      rgba(244,246,246,.32)
    );

  border: 1px solid rgba(255,255,255,.54);

  backdrop-filter:
    blur(24px)
    saturate(135%);

  -webkit-backdrop-filter:
    blur(24px)
    saturate(135%);

  box-shadow:
    0 12px 32px rgba(68,73,76,.12),
    inset 0 1px 0 rgba(255,255,255,.66);
}
```

Use sparingly.

---

# 4. Updated Color Tokens

Extend the existing palette.

```css
:root {
  /* Existing foundation */
  --bg: #d7d8d7;
  --surface: #dddddc;
  --surface-raised: #e0e1e0;

  /* Text */
  --text-primary: #4b4f51;
  --text-secondary: #676c6f;
  --text-muted: #85898b;

  /* Existing accents */
  --accent-blue: #4c6b73;
  --accent-green: #557762;
  --accent-red: #98666c;
  --accent-amber: #8d6e43;

  /* Glass */
  --glass-clear: rgba(250,252,252,.24);
  --glass-soft: rgba(247,249,249,.38);
  --glass-regular: rgba(244,246,246,.52);
  --glass-thick: rgba(239,241,241,.70);

  /* Glass lighting */
  --glass-highlight: rgba(255,255,255,.70);
  --glass-edge: rgba(255,255,255,.48);
  --glass-edge-soft: rgba(255,255,255,.26);

  /* Glass shadow */
  --glass-shadow: rgba(73,78,81,.12);
  --glass-shadow-deep: rgba(73,78,81,.17);

  /* Refraction/tint */
  --glass-blue-tint: rgba(106,143,151,.12);
  --glass-green-tint: rgba(94,132,106,.11);
  --glass-red-tint: rgba(146,91,99,.10);
  --glass-amber-tint: rgba(150,115,67,.11);
}
```

---

# 5. Glass Material Variants

Do not use one universal glass style.

Create a small material system.

## 5.1 Clear Glass

Use only over visually interesting or colored backgrounds.

```css
.glass-clear {
  background: rgba(255,255,255,.20);

  border: 1px solid rgba(255,255,255,.32);

  backdrop-filter:
    blur(14px)
    saturate(135%);

  -webkit-backdrop-filter:
    blur(14px)
    saturate(135%);

  box-shadow:
    0 8px 24px rgba(68,72,74,.08),
    inset 0 1px 0 rgba(255,255,255,.48);
}
```

Examples:

- floating icon button
- status bubble
- small badge
- temporary overlay

Avoid using this behind paragraphs of text.

## 5.2 Regular Glass

Default glass material.

```css
.glass-regular {
  background:
    linear-gradient(
      135deg,
      rgba(255,255,255,.52),
      rgba(242,245,245,.36)
    );

  border: 1px solid rgba(255,255,255,.48);

  backdrop-filter:
    blur(20px)
    saturate(125%);

  -webkit-backdrop-filter:
    blur(20px)
    saturate(125%);

  box-shadow:
    0 10px 28px rgba(70,75,78,.11),
    inset 0 1px 0 rgba(255,255,255,.67);
}
```

Examples:

- navigation
- coach action
- floating toolbar
- tab selector
- top status control

## 5.3 Thick Glass

Use for surfaces containing more text.

```css
.glass-thick {
  background:
    linear-gradient(
      135deg,
      rgba(248,250,250,.76),
      rgba(235,238,238,.64)
    );

  border: 1px solid rgba(255,255,255,.52);

  backdrop-filter:
    blur(24px)
    saturate(115%);

  -webkit-backdrop-filter:
    blur(24px)
    saturate(115%);

  box-shadow:
    0 14px 36px rgba(66,71,73,.13),
    inset 0 1px 0 rgba(255,255,255,.72);
}
```

Examples:

- menu
- popover
- modal
- context panel

---

# 6. Glass Should Have Optical Depth

Avoid plain:

```css
background: rgba(...);
backdrop-filter: blur(...);
```

by itself.

That usually creates generic glassmorphism.

Instead combine:

```text
translucency
+
blur
+
subtle saturation
+
edge highlight
+
soft outer shadow
+
internal highlight
```

Minimum recommended glass:

```css
.glass {
  background:
    linear-gradient(
      145deg,
      rgba(255,255,255,.48),
      rgba(240,243,243,.34)
    );

  backdrop-filter: blur(18px) saturate(125%);
  -webkit-backdrop-filter: blur(18px) saturate(125%);

  border: 1px solid rgba(255,255,255,.44);

  box-shadow:
    0 10px 30px rgba(70,75,78,.10),
    inset 0 1px 0 rgba(255,255,255,.65);
}
```

---

# 7. Specular Highlight

A major improvement over flat glass is a subtle highlight inside the upper edge.

Use a pseudo-element.

```css
.glass-specular {
  position: relative;
  overflow: hidden;
}

.glass-specular::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;

  border-radius: inherit;

  background:
    linear-gradient(
      145deg,
      rgba(255,255,255,.30) 0%,
      rgba(255,255,255,.10) 22%,
      transparent 45%
    );
}
```

Keep this subtle.

It should be noticed subconsciously.

---

# 8. Edge Lighting

Glass should have a bright upper edge and almost invisible lower edge.

```css
.glass-edge {
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.70),
    inset 1px 0 0 rgba(255,255,255,.20),
    inset 0 -1px 0 rgba(95,100,102,.05),
    0 10px 30px rgba(70,75,78,.10);
}
```

---

# 9. Floating Navigation

The existing navigation currently blends into the page.

Convert the main nav into a subtle floating glass strip.

```css
.top-nav {
  position: sticky;
  top: 16px;
  z-index: 50;

  display: flex;
  align-items: center;
  gap: 18px;

  width: fit-content;
  padding: 10px 14px;

  border-radius: 24px;

  background:
    linear-gradient(
      135deg,
      rgba(255,255,255,.48),
      rgba(242,244,244,.34)
    );

  border: 1px solid rgba(255,255,255,.42);

  backdrop-filter:
    blur(22px)
    saturate(130%);

  -webkit-backdrop-filter:
    blur(22px)
    saturate(130%);

  box-shadow:
    0 12px 34px rgba(70,75,78,.11),
    inset 0 1px 0 rgba(255,255,255,.66);
}
```

Do not turn the entire top page header into a giant glass rectangle.

Prefer smaller grouped floating elements.

---

# 10. Glass Navigation Item

Inactive:

```css
.nav-item {
  padding: 9px 13px;
  border-radius: 14px;
  color: var(--text-secondary);
}
```

Hover:

```css
.nav-item:hover {
  background: rgba(255,255,255,.22);
}
```

Active:

```css
.nav-item[aria-current="page"] {
  background:
    linear-gradient(
      145deg,
      rgba(255,255,255,.48),
      rgba(237,240,240,.30)
    );

  color: var(--text-primary);

  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.72),
    0 3px 10px rgba(75,80,82,.08);
}
```

---

# 11. Header Status Capsules

Elements like:

```text
SYNTHETIC FIXTURE
Live
Demo replay
idle
```

are ideal glass candidates.

```css
.status-capsule {
  display: inline-flex;
  align-items: center;
  gap: 8px;

  min-height: 34px;
  padding: 0 13px;

  border-radius: 999px;

  background: rgba(248,250,250,.38);

  border: 1px solid rgba(255,255,255,.46);

  backdrop-filter: blur(15px) saturate(120%);
  -webkit-backdrop-filter: blur(15px) saturate(120%);

  box-shadow:
    0 5px 14px rgba(75,80,82,.08),
    inset 0 1px 0 rgba(255,255,255,.65);
}
```

---

# 12. Brand / App Icon Orb

The round !Presh icon can become a more dimensional glass orb.

```css
.brand-orb {
  width: 52px;
  height: 52px;

  display: grid;
  place-items: center;

  border-radius: 50%;

  background:
    radial-gradient(
      circle at 32% 24%,
      rgba(255,255,255,.76),
      rgba(242,244,244,.48) 42%,
      rgba(220,222,222,.32)
    );

  border: 1px solid rgba(255,255,255,.50);

  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);

  box-shadow:
    0 8px 20px rgba(73,78,80,.10),
    inset 0 1px 0 rgba(255,255,255,.78);
}
```

---

# 13. Buttons

Current raised buttons are suitable for secondary content controls.

For primary actions such as:

```text
Ask coach to replan
```

use glass.

```css
.glass-button {
  position: relative;

  min-height: 48px;
  padding: 0 18px;

  border: 1px solid rgba(255,255,255,.48);
  border-radius: 18px;

  background:
    linear-gradient(
      145deg,
      rgba(255,255,255,.48),
      rgba(232,238,239,.34)
    );

  backdrop-filter:
    blur(18px)
    saturate(130%);

  -webkit-backdrop-filter:
    blur(18px)
    saturate(130%);

  color: var(--accent-blue);

  box-shadow:
    0 7px 18px rgba(65,75,78,.10),
    inset 0 1px 0 rgba(255,255,255,.72);

  transition:
    transform 140ms cubic-bezier(.2,.8,.2,1),
    box-shadow 140ms cubic-bezier(.2,.8,.2,1),
    background 140ms ease;
}
```

Hover:

```css
.glass-button:hover {
  transform: translateY(-1px);

  background:
    linear-gradient(
      145deg,
      rgba(255,255,255,.58),
      rgba(232,238,239,.39)
    );

  box-shadow:
    0 9px 22px rgba(65,75,78,.13),
    inset 0 1px 0 rgba(255,255,255,.78);
}
```

Pressed:

```css
.glass-button:active {
  transform: translateY(1px) scale(.99);

  box-shadow:
    0 3px 10px rgba(65,75,78,.09),
    inset 0 1px 4px rgba(90,98,100,.08);
}
```

---

# 14. Tinted Glass Actions

Tint important controls slightly according to semantic meaning.

Do not flood the entire control with color.

```css
.glass-blue {
  background:
    linear-gradient(
      145deg,
      rgba(255,255,255,.48),
      rgba(107,145,153,.12)
    );
}

.glass-green {
  background:
    linear-gradient(
      145deg,
      rgba(255,255,255,.48),
      rgba(92,132,106,.11)
    );
}

.glass-amber {
  background:
    linear-gradient(
      145deg,
      rgba(255,255,255,.48),
      rgba(155,118,66,.10)
    );
}

.glass-red {
  background:
    linear-gradient(
      145deg,
      rgba(255,255,255,.48),
      rgba(148,91,99,.10)
    );
}
```

Color should tint the material instead of looking painted onto it.

---

# 15. Segment Controls

A glass segmented control would suit:

```text
Vitals
Coach
Plan
Timeline
Tasks
```

or smaller dashboard filters.

```css
.segmented {
  display: inline-flex;
  gap: 4px;

  padding: 4px;

  border-radius: 18px;

  background: rgba(244,246,246,.34);

  border: 1px solid rgba(255,255,255,.38);

  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);

  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.54),
    0 5px 14px rgba(70,75,78,.07);
}

.segmented-item--active {
  background:
    linear-gradient(
      145deg,
      rgba(255,255,255,.60),
      rgba(238,241,241,.42)
    );

  border-radius: 14px;

  box-shadow:
    0 4px 10px rgba(69,74,76,.08),
    inset 0 1px 0 rgba(255,255,255,.74);
}
```

---

# 16. Glass Input Fields

For the coach prompt:

```text
Why was my Algorithms review moved?
```

replace the fully matte recessed surface with a semi-translucent well.

```css
.glass-input {
  min-height: 50px;
  padding: 0 17px;

  border-radius: 17px;

  border: 1px solid rgba(255,255,255,.32);

  background:
    rgba(244,246,246,.26);

  backdrop-filter:
    blur(14px)
    saturate(115%);

  -webkit-backdrop-filter:
    blur(14px)
    saturate(115%);

  box-shadow:
    inset 2px 2px 7px rgba(92,98,100,.07),
    inset -1px -1px 5px rgba(255,255,255,.36);
}

.glass-input:focus {
  border-color: rgba(74,110,118,.28);

  box-shadow:
    inset 2px 2px 7px rgba(92,98,100,.06),
    0 0 0 3px rgba(83,115,122,.10),
    inset 0 1px 0 rgba(255,255,255,.42);
}
```

---

# 17. Floating Icon Buttons

```css
.glass-icon-button {
  width: 42px;
  height: 42px;

  display: grid;
  place-items: center;

  border-radius: 50%;

  border: 1px solid rgba(255,255,255,.46);

  background:
    radial-gradient(
      circle at 32% 24%,
      rgba(255,255,255,.62),
      rgba(240,243,243,.34)
    );

  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);

  box-shadow:
    0 6px 16px rgba(71,76,78,.09),
    inset 0 1px 0 rgba(255,255,255,.74);
}
```

---

# 18. Panel Header Icon Treatment

```css
.panel-icon {
  width: 48px;
  height: 48px;

  display: grid;
  place-items: center;

  border-radius: 50%;

  background:
    radial-gradient(
      circle at 30% 20%,
      rgba(255,255,255,.60),
      rgba(231,234,234,.42)
    );

  border: 1px solid rgba(255,255,255,.40);

  box-shadow:
    -3px -3px 8px rgba(255,255,255,.30),
     4px  5px 12px rgba(116,121,123,.12),
    inset 0 1px 0 rgba(255,255,255,.65);
}
```

This preserves neumorphism while adding glass depth.

---

# 19. Calendar Panel

Do **not** turn the entire Weekly Plan into clear glass.

Keep the outer panel neumorphic.

Inside the panel:

```text
outer shell = neumorphic
calendar canvas = slightly translucent
events = softly tinted glass / material pills
```

```css
.calendar-surface {
  background:
    linear-gradient(
      145deg,
      rgba(246,247,247,.28),
      rgba(224,226,226,.20)
    );

  border: 1px solid rgba(255,255,255,.18);

  border-radius: 24px;

  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.30);
}
```

---

# 20. Calendar Event Materials

Events should become soft material tiles rather than flat rectangles.

```css
.calendar-event {
  border-radius: 9px;

  border: 1px solid rgba(255,255,255,.28);

  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);

  box-shadow:
    0 2px 6px rgba(72,77,79,.06),
    inset 0 1px 0 rgba(255,255,255,.30);
}

.calendar-event--study {
  background: rgba(107,143,151,.16);
  border-left: 3px solid rgba(70,105,113,.75);
}

.calendar-event--exam {
  background: rgba(151,91,100,.15);
  border-left: 3px solid rgba(139,74,83,.80);
}

.calendar-event--sleep {
  background: rgba(155,163,168,.12);
  border-left: 3px solid rgba(107,117,123,.64);
}

.calendar-event--recovery {
  background: rgba(91,132,105,.14);
  border-left: 3px solid rgba(73,112,87,.75);
}
```

---

# 21. Charts

Charts should stay visually grounded.

Do not put the chart itself on heavy glass.

Instead:

```text
outer card = neumorphic
chart plotting area = very faint inset material
legend / tooltip = glass
hover crosshair label = glass
```

```css
.chart-tooltip {
  padding: 10px 12px;

  border-radius: 12px;

  background: rgba(245,247,247,.58);

  border: 1px solid rgba(255,255,255,.48);

  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);

  box-shadow:
    0 8px 20px rgba(70,75,78,.11),
    inset 0 1px 0 rgba(255,255,255,.62);
}
```

---

# 22. Replan Recommendation Card

Recommended hierarchy:

```text
container = soft inset/neumorphic panel
reason chips = clear glass capsules
primary CTA = tinted glass button
```

```css
.reason-chip {
  display: inline-flex;
  align-items: center;

  min-height: 32px;
  padding: 0 12px;

  border-radius: 999px;

  background:
    linear-gradient(
      145deg,
      rgba(255,255,255,.38),
      rgba(151,112,66,.08)
    );

  border: 1px solid rgba(255,255,255,.36);

  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);

  box-shadow:
    0 3px 8px rgba(75,80,82,.05),
    inset 0 1px 0 rgba(255,255,255,.48);
}
```

---

# 23. Task Action Buttons

Buttons like:

```text
+15 min done
+30 min done
```

should look like small floating glass controls.

```css
.task-action {
  padding: 11px 15px;

  border-radius: 16px;

  background:
    linear-gradient(
      145deg,
      rgba(255,255,255,.48),
      rgba(237,240,240,.34)
    );

  border: 1px solid rgba(255,255,255,.40);

  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);

  box-shadow:
    0 6px 15px rgba(70,75,78,.08),
    inset 0 1px 0 rgba(255,255,255,.64);
}
```

---

# 24. Sticky Footer

The fixed disclaimer currently reads as a flat bar.

Turn it into a subtle frosted edge layer.

```css
.footer-glass {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;

  min-height: 42px;

  background: rgba(224,226,225,.64);

  backdrop-filter:
    blur(20px)
    saturate(110%);

  -webkit-backdrop-filter:
    blur(20px)
    saturate(110%);

  border-top: 1px solid rgba(255,255,255,.30);

  box-shadow:
    0 -8px 20px rgba(70,75,78,.05);
}
```

---

# 25. Scroll Edge Effect

Avoid hard separator lines at the top of scrolling panels.

Instead use a soft fading blur.

```css
.scroll-edge {
  position: sticky;
  top: 0;

  height: 18px;
  pointer-events: none;

  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);

  mask-image:
    linear-gradient(
      to bottom,
      black,
      transparent
    );
}
```

---

# 26. Hover Behavior

Glass should feel alive but not bouncy.

```css
transition:
  transform 160ms cubic-bezier(.2,.8,.2,1),
  background 160ms ease,
  box-shadow 160ms ease,
  border-color 160ms ease;
```

Hover:

```css
transform: translateY(-1px);
```

On hover, slightly increase:

```text
brightness
edge highlight
shadow
```

Do not dramatically increase opacity.

---

# 27. Press Behavior

```css
.glass-interactive:active {
  transform:
    translateY(1px)
    scale(.985);

  box-shadow:
    0 3px 9px rgba(70,75,78,.08),
    inset 0 2px 6px rgba(79,85,87,.08),
    inset 0 1px 0 rgba(255,255,255,.40);
}
```

---

# 28. Pointer Highlight

For high-value interactive controls only, optionally allow a very faint cursor-following highlight.

```css
background:
  radial-gradient(
    circle at var(--pointer-x) var(--pointer-y),
    rgba(255,255,255,.22),
    transparent 36%
  ),
  rgba(245,247,247,.36);
```

Use only for:

- primary glass buttons
- navigation shell
- major floating controls

Do not implement it on every card.

---

# 29. Motion Philosophy

Use motion to reinforce material.

Recommended durations:

```text
Hover       120–170ms
Press        80–120ms
Toggle      160–220ms
Popover     180–240ms
Panel       220–300ms
```

Recommended easing:

```css
cubic-bezier(.2,.8,.2,1)
```

Popovers:

```text
opacity 0 → 1
scale .97 → 1
translateY 4px → 0
```

Avoid exaggerated spring animations.

---

# 30. Optional Framer Motion

```bash
npm install framer-motion
```

```tsx
<motion.div
  initial={{ opacity: 0, y: 4, scale: 0.98 }}
  animate={{ opacity: 1, y: 0, scale: 1 }}
  exit={{ opacity: 0, y: 3, scale: 0.98 }}
  transition={{
    duration: 0.18,
    ease: [0.2, 0.8, 0.2, 1]
  }}
/>
```

---

# 31. Blur Performance Rules

`backdrop-filter` can be expensive.

Do not:

```text
blur every card
blur huge full-screen surfaces
stack 4+ blurred layers
animate blur continuously
```

Prefer:

```text
small floating surfaces
nav
toolbar
popover
status capsules
sticky footer
controls
```

Use approximately:

```text
8–12px   subtle component
14–18px  small floating control
18–24px  navigation / popover
24–30px  modal only
```

---

# 32. Browser Fallback

```css
.glass {
  background: rgba(239,241,241,.88);
}

@supports (
  (backdrop-filter: blur(1px)) or
  (-webkit-backdrop-filter: blur(1px))
) {
  .glass {
    background: rgba(244,246,246,.42);

    backdrop-filter:
      blur(18px)
      saturate(125%);

    -webkit-backdrop-filter:
      blur(18px)
      saturate(125%);
  }
}
```

---

# 33. Reduced Transparency

```css
@media (prefers-reduced-transparency: reduce) {
  .glass,
  .glass-regular,
  .glass-clear,
  .glass-thick {
    backdrop-filter: none;
    -webkit-backdrop-filter: none;

    background: rgba(239,241,241,.96);
  }
}
```

Browser support varies, so also support an application-level accessibility preference if practical.

---

# 34. Reduced Motion

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: .01ms !important;
    transition-duration: .01ms !important;
  }
}
```

---

# 35. Contrast

Glass must never make content hard to read.

For body text:

```css
color: #4b4f51;
```

For secondary text:

```css
color: #686d70;
```

If the surface becomes more transparent, the foreground must become more opaque.

---

# 36. Blur + Text Rule

Use the following rule:

```text
More text
→
more opaque material
→
less background interference
```

Examples:

```text
icon button       → clear glass
status badge      → clear/regular glass
navigation        → regular glass
popover           → regular/thick glass
modal paragraph   → thick glass
```

---

# 37. Depth Hierarchy

Limit the system to approximately four visual elevations.

## Elevation 0
Background.

## Elevation 1
Neumorphic content panel.

## Elevation 2
Raised interior control.

## Elevation 3
Glass control.

## Elevation 4
Popover/modal.

Never give everything maximum elevation.

---

# 38. Difference Between Neumorphic and Glass Shadows

Neumorphic components:

```text
upper-left light shadow
+
lower-right dark shadow
```

Glass components:

```text
mostly downward ambient shadow
+
bright internal top edge
```

This difference makes glass controls appear to float **above** the molded neumorphic layer.

---

# 39. Hybrid Component

```css
.hybrid-surface {
  background:
    linear-gradient(
      145deg,
      rgba(255,255,255,.34),
      rgba(218,221,221,.42)
    );

  border: 1px solid rgba(255,255,255,.30);

  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);

  box-shadow:
    -4px -4px 10px rgba(255,255,255,.28),
     6px  7px 16px rgba(117,122,124,.13),
    inset 0 1px 0 rgba(255,255,255,.52);
}
```

Ideal for:

- panel header icons
- small metrics
- controls inside cards

---

# 40. Recommended UI Conversion for the Current !Presh Screens

Based on the current interface, update components as follows.

```text
APP BACKGROUND
Keep neumorphic gray.
Add extremely subtle ambient radial gradients.

LOGO ORB
Hybrid glass/neumorphic orb.

MAIN NAVIGATION
Glass floating toolbar.

CURRENT TIME
Keep text directly on background.
Optionally place clock icon in tiny glass icon well.

SYNTHETIC FIXTURE
Glass capsule.

LIVE STATUS
Keep minimal.
No large container required.

DEMO REPLAY
Glass toolbar/control.

PHYSIOLOGY
Keep neumorphic.

LOAD GAUGE
Keep neumorphic.

HEART RATE
Keep neumorphic.

RECOVERY / ACTIVITY / REST
Keep mostly neumorphic.
Small status icons can use hybrid glass wells.

WEEKLY PLAN
Keep outer container neumorphic.

CALENDAR
Subtle inset material.

CALENDAR EVENTS
Tinted semi-transparent material.

REPLAN RECOMMENDED
Keep structural shell neumorphic.
Convert tags to glass chips.

ASK COACH TO REPLAN
Tinted glass primary CTA.

COACH INPUT
Inset translucent glass.

TASKS
Keep panel neumorphic.

TASK ACTION BUTTONS
Glass.

WEARABLE TIMELINE
Keep outer panel neumorphic.

CHART
Keep simple and matte.

CHART TOOLTIP
Glass.

FOOTER DISCLAIMER
Frosted translucent sticky bar.
```

---

# 41. Suggested Component Architecture

Extend the existing component library.

```text
components/
  ui/
    NeuCard.tsx
    NeuButton.tsx
    NeuInput.tsx

    GlassSurface.tsx
    GlassButton.tsx
    GlassIconButton.tsx
    GlassBadge.tsx
    GlassInput.tsx
    GlassToolbar.tsx
    GlassPopover.tsx
    GlassSegmentedControl.tsx

    HybridIconWell.tsx
```

Do not duplicate styling in feature components.

---

# 42. GlassSurface API

```tsx
type GlassVariant =
  | "clear"
  | "regular"
  | "thick";

type GlassTint =
  | "neutral"
  | "blue"
  | "green"
  | "red"
  | "amber";

interface GlassSurfaceProps {
  variant?: GlassVariant;
  tint?: GlassTint;
  interactive?: boolean;
  className?: string;
  children: React.ReactNode;
}
```

Usage:

```tsx
<GlassSurface
  variant="regular"
  tint="blue"
  interactive
>
  Ask coach to replan
</GlassSurface>
```

---

# 43. CSS Utility Classes

```css
.glass-clear {}
.glass-regular {}
.glass-thick {}

.glass-blue {}
.glass-green {}
.glass-red {}
.glass-amber {}

.glass-interactive {}
.glass-specular {}

.neu-raised {}
.neu-inset {}

.hybrid-surface {}
```

Keep material definitions centralized.

---

# 44. Tailwind Example

If the project uses Tailwind, define material utilities rather than repeating arbitrary values.

```js
extend: {
  colors: {
    neu: {
      bg: "#d7d8d7",
      surface: "#dddddc",
      text: "#4b4f51"
    }
  },

  boxShadow: {
    neu:
      "-10px -10px 24px rgba(255,255,255,.52), 10px 10px 24px rgba(137,140,140,.25)",

    glass:
      "0 10px 28px rgba(70,75,78,.11), inset 0 1px 0 rgba(255,255,255,.67)",

    "glass-lg":
      "0 14px 36px rgba(66,71,73,.13), inset 0 1px 0 rgba(255,255,255,.72)"
  },

  backdropBlur: {
    glass: "18px",
    "glass-lg": "24px"
  }
}
```

---

# 45. Optional CSS Noise

Real glass/material surfaces can benefit from an almost invisible texture.

Keep opacity extremely low.

```css
.glass-texture::after {
  content: "";
  position: absolute;
  inset: 0;

  pointer-events: none;
  border-radius: inherit;

  opacity: .015;
}
```

---

# 46. Optional Background Color Bleed

A glass component should subtly inherit nearby colors.

```css
.glass-blue {
  background:
    linear-gradient(
      145deg,
      rgba(255,255,255,.46),
      rgba(79,111,119,.10)
    );
}
```

Avoid large saturated colored glass blocks.

---

# 47. Do Not Copy iOS Literally

The goal is Apple-inspired material behavior, not an iPhone clone.

Do not add:

- iOS home indicators
- iPhone-style tab bars where they make no sense
- oversized iOS switches everywhere
- San Francisco typography solely to imitate Apple
- macOS traffic-light controls
- fake window chrome

This is still the **!Presh product identity**.

---

# 48. Recommended Dependencies

The glass look should mostly be native CSS.

```bash
npm install lucide-react
npm install @fontsource/inter
npm install framer-motion
```

Optional:

```bash
npm install clsx
npm install tailwind-merge
```

Do not install a dedicated glassmorphism UI library.

---

# 49. Accessibility Checklist

Before accepting any glass component:

- [ ] Text remains readable over all possible backgrounds
- [ ] Interactive state isn't represented by transparency alone
- [ ] Focus ring is obvious
- [ ] Icon buttons have accessible names
- [ ] Touch targets remain at least approximately 44 × 44px
- [ ] Reduced motion is respected
- [ ] Reduced transparency has a fallback
- [ ] Blur doesn't obscure important information
- [ ] Important medical/wellness disclaimers remain readable
- [ ] Status colors are paired with labels or icons

---

# 50. Performance Checklist

Before shipping:

- [ ] Avoid full-page backdrop blur
- [ ] Do not animate `backdrop-filter`
- [ ] Avoid multiple nested blurred elements
- [ ] Use glass primarily for smaller floating controls
- [ ] Test scrolling performance
- [ ] Test Safari
- [ ] Test Chromium
- [ ] Add opaque fallbacks
- [ ] Keep blur radius under control
- [ ] Reduce unnecessary box-shadow layers

---

# 51. Visual QA Checklist

The glass enhancement is successful when:

- [ ] Main content still looks neumorphic
- [ ] Controls visibly float above content
- [ ] Navigation feels lighter than dashboard cards
- [ ] Blur is noticeable but restrained
- [ ] Upper edges catch light
- [ ] Shadows are soft
- [ ] Accent colors tint glass rather than paint it
- [ ] Calendar event blocks have more depth
- [ ] Buttons feel tactile
- [ ] The footer appears layered above scrolling content
- [ ] There are no giant transparent glass cards everywhere
- [ ] Interface remains calm and readable
- [ ] The UI still works when all glass effects are disabled

---

# 52. AI Coding-Agent Prompt

> Preserve the existing light neumorphic !Presh design system, but introduce a second material layer inspired by modern Apple translucent interface design. Do not convert the entire app to generic glassmorphism. Keep data-rich content cards such as Physiology, Weekly Plan, Tasks, and Wearable Timeline as mostly opaque neumorphic surfaces. Use translucent glass primarily for controls and navigation: the main nav, Demo Replay control, status capsules, CTA buttons, small action buttons, inputs, tooltips, menus, popovers, and the sticky footer. Glass surfaces should use restrained translucency, 14–24px backdrop blur, slight saturation, a bright upper-edge highlight, a subtle white border, a soft conventional downward shadow, and optional very low-opacity semantic tinting. Neumorphic surfaces should retain their existing opposing upper-left highlight and lower-right shadow. This difference in shadow behavior should make glass controls visibly float above the content layer. Add subtle ambient gradients to the page background so translucency has something to refract visually. Keep the visual palette neutral and low-saturation. Avoid giant glass panels, neon gradients, strong borders, high transparency behind text, and excessive blur. All controls must remain accessible and responsive.

---

# 53. Short Agent Implementation Order

Implement in this order:

1. Add glass design tokens.
2. Add `.glass-clear`, `.glass-regular`, and `.glass-thick`.
3. Add a reusable `GlassSurface`.
4. Convert the top navigation to glass.
5. Convert Demo Replay to glass.
6. Convert Synthetic Fixture to a glass capsule.
7. Convert Ask Coach to Replan to tinted glass.
8. Convert task action buttons to glass.
9. Convert coach input to translucent inset glass.
10. Convert calendar events to light material tiles.
11. Add glass chart tooltips.
12. Add frosted sticky footer.
13. Add fallback for browsers without backdrop blur.
14. Verify contrast and keyboard focus.
15. Tune opacity/blur only after testing the full page.

---

# 54. Recommended Starting Values

If the first implementation looks too flat:

```text
increase edge highlight slightly
increase downward shadow slightly
add ambient background gradients
```

Do **not** immediately increase blur.

If it looks too glassy:

```text
increase opacity
reduce blur
remove glass from content cards
reduce borders
```

If it looks washed out:

```text
darken text
reduce background opacity
increase local contrast
```

If it looks like generic glassmorphism:

```text
remove large glass cards
reduce saturation
keep only controls glass
restore neumorphic content surfaces
add subtle upper-edge specular highlights
```

---

# 55. Final Material Formula

```text
Background
  ↓
warm gray ambient plane

Content
  ↓
soft molded neumorphic surfaces

Controls
  ↓
translucent floating glass

Interaction
  ↓
subtle light response + compression

Color
  ↓
small semantic tint only
```

The intended result is **not** pure neumorphism and **not** pure glassmorphism.

It is a hybrid material system in which:

> Neumorphism provides softness and physical structure, while glass provides hierarchy, motion, translucency, and premium depth.

---

# 56. Design References

The implementation direction in this guide is informed by Apple's current design guidance around materials and Liquid Glass:

- Apple Human Interface Guidelines — Materials  
  https://developer.apple.com/design/human-interface-guidelines/materials

- Apple Human Interface Guidelines — Layout  
  https://developer.apple.com/design/human-interface-guidelines/layout

- Apple Developer — Meet Liquid Glass, WWDC25  
  https://developer.apple.com/videos/play/wwdc2025/219/

Use these as **design principles**, not as instructions to reproduce Apple system UI literally.
