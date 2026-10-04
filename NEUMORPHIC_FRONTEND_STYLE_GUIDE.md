# Neumorphic Frontend UI Style Guide
## Reference: Soft-Monochrome Smart Home Dashboard

Use this document as the visual system prompt for the entire frontend. The goal is to reproduce the **soft, tactile, monochrome neumorphic look** shown in the supplied reference image: a warm light-gray canvas, large rounded surfaces, soft directional shadows, subtle inset controls, minimal color, and very restrained typography.

The interface should feel like **physical controls molded from one continuous material**, not like ordinary cards placed on a page.

---

# 1. Core Visual Direction

## Design language

Build the UI around these principles:

- **Neumorphism / soft UI**
- Light warm-gray background
- Raised cards that appear extruded from the same background material
- Soft top-left highlight + soft bottom-right shadow
- Little to no visible border
- Large rounded corners
- Low visual contrast
- Minimal use of color
- Dark charcoal text, never pure black
- Sparse accent color used only for status, selected states, or tiny illustrations
- Generous spacing
- Simple iconography
- Calm, premium, appliance-control feel
- Avoid glossy glassmorphism, bright gradients, sharp lines, or flat Material-style cards

The visual hierarchy should come primarily from:

1. Surface depth
2. Spacing
3. Typography weight
4. Size
5. Only then, color

---

# 2. Reference Palette

The supplied reference is dominated by neutral grays. Use these as the baseline design tokens.

```css
:root {
  /* Main surfaces */
  --bg: #d9d9d9;
  --surface: #dddddd;
  --surface-raised: #dedede;
  --surface-hover: #e1e1e1;

  /* Neumorphic lighting */
  --highlight: rgba(255, 255, 255, 0.72);
  --highlight-soft: rgba(255, 255, 255, 0.40);
  --shadow: rgba(154, 154, 154, 0.42);
  --shadow-deep: rgba(128, 128, 128, 0.28);

  /* Text */
  --text-primary: #4a4d4f;
  --text-secondary: #777a7c;
  --text-muted: #999c9e;
  --text-disabled: #b0b2b3;

  /* Optional status/accent palette */
  --accent: #415e66;
  --accent-muted: #60777d;
  --success: #668071;
  --warning: #9a8060;
  --danger: #8d6266;

  /* Optional extremely subtle separator */
  --separator: rgba(80, 80, 80, 0.07);
}
```

## Color usage rules

- Approximately **90–95% of the interface should remain neutral gray**.
- Accent colors should occupy only a very small visual area.
- Never use large saturated panels.
- Avoid pure `#000000` and pure `#ffffff` for major UI surfaces.
- White should appear mainly as a lighting highlight, not as a flat surface color.
- If a dark theme is later added, create a separate system rather than simply inverting these values.

---

# 3. Lighting Model

Neumorphism works only if every component follows the same imaginary light source.

## Global light direction

Assume light comes from the **upper-left**.

That means:

- Upper-left edge = brighter
- Lower-right edge = darker
- Raised objects cast a shadow down/right
- Pressed objects reverse the effect with inset shadows

Do not randomly change shadow directions between components.

---

# 4. Core Shadow Tokens

## Raised card

Use for large cards and primary panels.

```css
--shadow-raised:
  -10px -10px 22px rgba(255, 255, 255, 0.56),
   10px  10px 22px rgba(150, 150, 150, 0.34);
```

Example:

```css
.neu-card {
  background: var(--surface);
  border-radius: 28px;
  box-shadow:
    -10px -10px 22px rgba(255,255,255,.56),
     10px  10px 22px rgba(150,150,150,.34);
}
```

## Medium raised surface

Use for scene tiles, compact cards, list rows, pills.

```css
box-shadow:
  -6px -6px 14px rgba(255,255,255,.52),
   6px  6px 14px rgba(148,148,148,.30);
```

## Small raised control

Use for circular icon buttons and small toggle shells.

```css
box-shadow:
  -4px -4px 9px rgba(255,255,255,.55),
   4px  4px 9px rgba(145,145,145,.28);
```

## Pressed / inset surface

Use for active buttons, recessed controls, tracks, selected inputs.

```css
box-shadow:
  inset 4px 4px 8px rgba(145,145,145,.22),
  inset -4px -4px 8px rgba(255,255,255,.52);
```

## Deep inset well

Use sparingly for sliders or prominent recessed areas.

```css
box-shadow:
  inset 6px 6px 12px rgba(140,140,140,.24),
  inset -6px -6px 12px rgba(255,255,255,.50);
```

---

# 5. Border Rules

The reference UI does not rely on visible borders.

Default:

```css
border: 1px solid rgba(255,255,255,0.15);
```

or:

```css
border: none;
```

If a border is necessary for accessibility, make it subtle:

```css
border: 1px solid rgba(70,70,70,.08);
```

Never use strong dark card borders.

---

# 6. Border Radius System

Use generously rounded corners.

```css
--radius-xs: 10px;
--radius-sm: 14px;
--radius-md: 18px;
--radius-lg: 24px;
--radius-xl: 28px;
--radius-2xl: 34px;
--radius-pill: 999px;
```

Recommended usage:

- Large dashboard cards: `28–34px`
- Scene tiles: `22–28px`
- List rows: `18–24px`
- Buttons: `16–22px`
- Small icon buttons: circular
- Pills/toggles: `999px`

Avoid square corners.

---

# 7. Typography

The reference uses a clean geometric sans-serif with restrained weight.

## Recommended fonts

Preferred:

```text
Inter
```

Strong alternatives:

```text
Manrope
SF Pro Display / SF Pro Text
Geist
DM Sans
```

For web projects, use **Inter** unless the product already has a typeface.

### Suggested package

```bash
npm install @fontsource/inter
```

or import from Google Fonts.

## Font rules

```css
body {
  font-family:
    "Inter",
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;

  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
```

## Type scale

```css
--text-xs: 0.72rem;
--text-sm: 0.82rem;
--text-base: 0.95rem;
--text-md: 1.05rem;
--text-lg: 1.25rem;
--text-xl: 1.65rem;
--text-display: 2.6rem;
```

Use:

- Main metric/value: `2.2–3rem`, weight `500–600`
- Card title: `0.95–1.05rem`, weight `600`
- Supporting text: `0.75–0.85rem`, weight `400–500`
- Tiny metadata: `0.68–0.76rem`, weight `450–500`

Avoid excessively bold typography. Most UI labels should use `500` or `600`.

---

# 8. Spacing System

Base all spacing on a 4px rhythm.

```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 20px;
--space-6: 24px;
--space-8: 32px;
--space-10: 40px;
--space-12: 48px;
```

Typical card padding:

```text
24–32px desktop
20–24px tablet
16–20px mobile
```

The UI should feel spacious. Do not pack controls tightly.

---

# 9. Page Background

Use one continuous matte background.

```css
html,
body,
#root {
  min-height: 100%;
  background: #d9d9d9;
}
```

For full viewport layouts:

```css
.app-shell {
  min-height: 100vh;
  background: var(--bg);
  padding: clamp(20px, 4vw, 56px);
}
```

Do not place large white containers over this background.

---

# 10. Dashboard Layout

The reference uses an asymmetrical two-column composition:

- Left: main device control
- Right: analytics/device list
- Smaller scene cards beneath main control
- Utility/status row below

Recommended desktop structure:

```css
.dashboard {
  width: min(1180px, 100%);
  margin-inline: auto;

  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(340px, .95fr);
  gap: 28px;
  align-items: start;
}
```

Use nested grids for smaller cards:

```css
.scene-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 18px;
}
```

Responsive behavior:

```css
@media (max-width: 900px) {
  .dashboard {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 560px) {
  .scene-grid {
    grid-template-columns: 1fr;
  }
}
```

---

# 11. Large Feature Card

The main feature card should look carved from the background.

```css
.feature-card {
  position: relative;
  padding: 26px 28px 30px;
  border-radius: 30px;
  background: var(--surface);
  box-shadow:
    -10px -10px 24px rgba(255,255,255,.58),
     11px  11px 24px rgba(145,145,145,.34);
}
```

Recommended composition:

```text
Header row
  icon
  title/subtitle
  status/toggle

Visualization / control
  large numeric metric
  supporting label
```

Keep large controls visually centered and uncluttered.

---

# 12. Compact Scene Cards

Scene cards should be soft blocks with only one icon and a small amount of copy.

```css
.scene-card {
  min-height: 150px;
  padding: 20px;
  border-radius: 24px;
  background: var(--surface);
  box-shadow:
    -7px -7px 16px rgba(255,255,255,.52),
     7px  7px 16px rgba(148,148,148,.29);
}
```

Hover:

```css
.scene-card:hover {
  transform: translateY(-1px);
  box-shadow:
    -8px -8px 18px rgba(255,255,255,.58),
     8px  8px 18px rgba(145,145,145,.33);
}
```

Active/pressed:

```css
.scene-card:active {
  transform: translateY(0);
  box-shadow:
    inset 4px 4px 9px rgba(145,145,145,.22),
    inset -4px -4px 9px rgba(255,255,255,.50);
}
```

---

# 13. List Rows

Device list rows should appear as small raised pills inside a larger raised card.

```css
.neu-list-item {
  display: flex;
  align-items: center;
  min-height: 58px;
  padding: 10px 14px;
  border-radius: 20px;
  background: var(--surface);
  box-shadow:
    -5px -5px 11px rgba(255,255,255,.48),
     5px  5px 11px rgba(145,145,145,.28);
}
```

Layout:

```text
[icon well] [title + metadata] [chevron]
```

Each row should have enough empty space to maintain the soft aesthetic.

---

# 14. Icon Wells

Icons should often sit in a small circular or rounded recessed/raised area.

Raised icon:

```css
.icon-well {
  width: 38px;
  height: 38px;

  display: grid;
  place-items: center;

  border-radius: 50%;
  background: var(--surface);

  box-shadow:
    -4px -4px 8px rgba(255,255,255,.50),
     4px  4px 8px rgba(145,145,145,.25);
}
```

Inset icon:

```css
.icon-well--inset {
  box-shadow:
    inset 3px 3px 6px rgba(145,145,145,.18),
    inset -3px -3px 6px rgba(255,255,255,.46);
}
```

---

# 15. Icons

Use thin, simple line icons.

## Recommended library

```bash
npm install lucide-react
```

Preferred defaults:

```tsx
<Icon
  size={18}
  strokeWidth={1.7}
/>
```

Rules:

- `16–20px` for ordinary controls
- `20–26px` for prominent icons
- Avoid filled icons unless indicating selected state
- Use `currentColor`
- Icon color should usually be `var(--text-secondary)`

Do not mix icon libraries unless unavoidable.

---

# 16. Buttons

## Raised secondary button

```css
.neu-button {
  min-height: 40px;
  padding: 0 16px;

  border: 0;
  border-radius: 16px;
  background: var(--surface);

  color: var(--text-secondary);
  font: inherit;
  font-size: .82rem;
  font-weight: 600;

  box-shadow:
    -4px -4px 9px rgba(255,255,255,.54),
     4px  4px 9px rgba(145,145,145,.28);

  transition:
    transform 140ms ease,
    box-shadow 140ms ease;
}
```

Pressed state:

```css
.neu-button:active,
.neu-button[aria-pressed="true"] {
  box-shadow:
    inset 3px 3px 7px rgba(145,145,145,.23),
    inset -3px -3px 7px rgba(255,255,255,.48);
}
```

---

# 17. Toggle Switch

The screenshot uses very understated state controls.

Recommended structure:

```html
<button class="neu-toggle" aria-pressed="true">
  <span class="neu-toggle__thumb"></span>
</button>
```

CSS:

```css
.neu-toggle {
  width: 54px;
  height: 30px;
  padding: 4px;

  border: 0;
  border-radius: 999px;
  background: var(--surface);

  box-shadow:
    inset 3px 3px 7px rgba(145,145,145,.20),
    inset -3px -3px 7px rgba(255,255,255,.45);
}

.neu-toggle__thumb {
  display: block;
  width: 22px;
  height: 22px;

  border-radius: 50%;
  background: #e2e2e2;

  box-shadow:
    -2px -2px 5px rgba(255,255,255,.60),
     2px  2px 5px rgba(145,145,145,.32);

  transition: transform 180ms ease;
}

.neu-toggle[aria-pressed="true"] .neu-toggle__thumb {
  transform: translateX(24px);
}
```

If using color for the on state, keep it muted.

---

# 18. Inputs

Inputs should look slightly recessed.

```css
.neu-input {
  width: 100%;
  min-height: 46px;
  padding: 0 16px;

  border: 0;
  outline: none;
  border-radius: 16px;

  background: var(--surface);
  color: var(--text-primary);

  box-shadow:
    inset 4px 4px 8px rgba(145,145,145,.18),
    inset -4px -4px 8px rgba(255,255,255,.48);
}
```

Focus state:

```css
.neu-input:focus-visible {
  outline: 2px solid rgba(65,94,102,.42);
  outline-offset: 3px;
}
```

Never remove visible keyboard focus completely.

---

# 19. Circular Metric / Gauge Style

For radial controls like the temperature control in the reference:

- Keep labels sparse
- Use a wide arc, not a full circle
- Use many thin ticks
- Differentiate active ticks primarily with darkness, not bright color
- Place the numeric value at the visual center
- Keep secondary labels tiny

Example active/inactive tick colors:

```css
--gauge-active: #55595b;
--gauge-inactive: #b5b7b8;
```

If drawing gauges:

Preferred options:

- SVG
- CSS conic gradients for simple indicators
- Canvas only if data density requires it

SVG is recommended because it gives precise control over tick marks and accessibility.

---

# 20. Charts and Data Visualization

Charts should fit the same soft language.

Rules:

- Minimal axis lines
- No heavy chart borders
- Muted gray gridlines
- One subdued accent color
- Rounded line joins
- Avoid rainbow palettes
- Prefer sparklines and simple radial indicators
- Keep chart background transparent so it visually belongs to the card

Example chart colors:

```css
--chart-primary: #596f75;
--chart-secondary: #8a9699;
--chart-grid: rgba(70,70,70,.08);
```

---

# 21. Interaction States

Every interactive neumorphic control should have a physical-feeling response.

## Resting

Raised.

## Hover

Slightly more elevated.

```css
transform: translateY(-1px);
```

## Pressed

Inset.

```css
box-shadow:
  inset 3px 3px 7px rgba(145,145,145,.22),
  inset -3px -3px 7px rgba(255,255,255,.48);
```

## Disabled

Reduce contrast without eliminating shape.

```css
opacity: .48;
cursor: not-allowed;
```

---

# 22. Motion

Recommended:

```bash
npm install framer-motion
```

This is optional; CSS transitions are sufficient for most controls.

Motion should feel subtle and mechanical.

Recommended durations:

```text
Hover: 120–160ms
Press: 80–120ms
Toggle: 160–220ms
Panel transitions: 220–320ms
```

Use easing such as:

```css
cubic-bezier(.2,.8,.2,1)
```

Avoid bouncy spring effects for ordinary controls.

Respect reduced motion:

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

# 23. Accessibility Requirements

Neumorphism can create contrast problems. Do not sacrifice usability to preserve the style.

Required:

- Maintain readable text contrast
- Use semantic buttons and controls
- Add clear keyboard focus rings
- Never communicate state using shadow alone
- Pair state changes with icon, text, or `aria-pressed`
- Ensure touch targets are at least approximately `44 × 44px`
- Use labels for icon-only controls
- Use `aria-label` where visual text is absent
- Respect reduced motion
- Do not use low-contrast gray for critical information

For important text, prefer:

```css
color: #4a4d4f;
```

rather than the lighter decorative grays.

---

# 24. Recommended Frontend Dependencies

The aesthetic itself should be implemented with CSS. Do not depend on a heavy UI component framework.

Recommended:

```bash
npm install lucide-react
npm install @fontsource/inter
npm install framer-motion
```

Optional, depending on the stack:

```bash
npm install clsx
npm install tailwind-merge
```

If using Tailwind CSS, keep custom neumorphic shadows in the design tokens instead of stacking arbitrary shadow utilities everywhere.

Avoid importing a large component system such as Material UI solely for this visual style, because its defaults will fight the neumorphic design language.

---

# 25. Tailwind Token Example

If using Tailwind, define named utilities instead of repeated arbitrary values.

Example conceptual configuration:

```js
theme: {
  extend: {
    colors: {
      neu: {
        bg: "#d9d9d9",
        surface: "#dddddd",
        text: "#4a4d4f",
        muted: "#777a7c",
        accent: "#415e66",
      },
    },
    borderRadius: {
      neu: "28px",
    },
    boxShadow: {
      neu: "-10px -10px 22px rgba(255,255,255,.56), 10px 10px 22px rgba(150,150,150,.34)",
      "neu-sm": "-5px -5px 11px rgba(255,255,255,.50), 5px 5px 11px rgba(145,145,145,.28)",
      "neu-inset": "inset 4px 4px 8px rgba(145,145,145,.22), inset -4px -4px 8px rgba(255,255,255,.52)",
    },
  },
}
```

---

# 26. React Component Architecture

Keep visual primitives reusable.

Recommended folder structure:

```text
src/
  components/
    ui/
      NeuCard.tsx
      NeuButton.tsx
      NeuIconButton.tsx
      NeuInput.tsx
      NeuToggle.tsx
      NeuListItem.tsx
      IconWell.tsx
      Metric.tsx

    dashboard/
      DeviceCard.tsx
      DeviceList.tsx
      SceneCard.tsx
      Gauge.tsx
      AnalyticsCard.tsx

  styles/
    tokens.css
    neumorphism.css
    globals.css
```

The reusable primitives should contain the depth behavior. Feature components should not invent new shadow styles.

---

# 27. Core Reusable CSS Classes

```css
.neu-raised {
  background: var(--surface);
  box-shadow:
    -10px -10px 22px rgba(255,255,255,.56),
     10px  10px 22px rgba(150,150,150,.34);
}

.neu-raised-sm {
  background: var(--surface);
  box-shadow:
    -5px -5px 11px rgba(255,255,255,.50),
     5px  5px 11px rgba(145,145,145,.28);
}

.neu-inset {
  background: var(--surface);
  box-shadow:
    inset 4px 4px 8px rgba(145,145,145,.22),
    inset -4px -4px 8px rgba(255,255,255,.52);
}

.neu-interactive {
  transition:
    transform 140ms cubic-bezier(.2,.8,.2,1),
    box-shadow 140ms cubic-bezier(.2,.8,.2,1);
}

.neu-interactive:hover {
  transform: translateY(-1px);
}

.neu-interactive:active {
  transform: translateY(0);
  box-shadow:
    inset 3px 3px 7px rgba(145,145,145,.22),
    inset -3px -3px 7px rgba(255,255,255,.48);
}
```

---

# 28. Visual Density Rules

The screenshot succeeds because it is not cluttered.

Follow these rules:

- Each card should communicate one primary idea
- Limit each card to one major metric or action
- Avoid excessive text
- Use 2–3 typography levels per card maximum
- Keep a minimum of `16px` between unrelated controls
- Keep outer panel gaps around `24–30px` on desktop
- Do not fill empty space simply because it exists
- Prefer composition over decoration

---

# 29. Image and Illustration Treatment

If an avatar, product image, or illustration is included:

- Keep it small
- Place it inside a circular raised/inset frame
- Use subdued colors
- Avoid large photography backgrounds
- Avoid strong image shadows that conflict with the neumorphic lighting model

Example:

```css
.avatar-shell {
  padding: 5px;
  border-radius: 50%;
  background: var(--surface);

  box-shadow:
    -5px -5px 10px rgba(255,255,255,.55),
     5px  5px 10px rgba(145,145,145,.30);
}
```

---

# 30. Responsive Design Rules

Desktop should preserve the spacious horizontal composition.

Tablet:

- Collapse complex two-column areas when necessary
- Keep card radii large
- Preserve at least `20px` outer padding

Mobile:

- Single-column layout
- Full-width cards
- Reduce shadows slightly
- Reduce large card radius from `28–34px` to `22–26px`
- Keep touch targets large
- Do not shrink labels below readable sizes

Example:

```css
@media (max-width: 640px) {
  :root {
    --mobile-card-radius: 24px;
  }

  .app-shell {
    padding: 18px;
  }

  .neu-card {
    border-radius: var(--mobile-card-radius);
  }
}
```

---

# 31. Neumorphism Anti-Patterns

Do **not** do the following:

- Pure-white cards on a gray background
- Black drop shadows
- Strong 1px borders around every component
- Random shadow directions
- Extremely blurred shadows that resemble fog
- Very high elevation
- Bright gradients on all cards
- Glassmorphism blur
- Excessive saturated accent colors
- Heavy use of pure black
- Sharp corners
- Flat Material Design buttons
- Strong box outlines
- Tiny low-contrast body text
- Using shadow alone to communicate enabled/disabled state
- More than 3–4 distinct elevation levels

---

# 32. Visual QA Checklist

Before considering a page finished, verify:

- [ ] Background and cards feel like the same material
- [ ] All raised surfaces use the same upper-left light direction
- [ ] All shadows are soft and neutral
- [ ] No card has a harsh border
- [ ] Corner radii are consistently generous
- [ ] Text is charcoal rather than black
- [ ] Secondary text is visually quieter than primary text
- [ ] Accent color is used sparingly
- [ ] Interactive elements visibly depress on click/tap
- [ ] Focus states remain keyboard-accessible
- [ ] No component uses an unrelated design language
- [ ] Layout contains ample negative space
- [ ] Mobile version remains usable and touch-friendly
- [ ] Important states are not indicated by shadow alone
- [ ] All icons come from the same icon family
- [ ] The UI still looks coherent in grayscale

---

# 33. Agent / AI Implementation Prompt

Use the following as the high-level instruction for any coding agent working on this frontend:

> Build the frontend using a restrained light **neumorphic / soft-UI design system** modeled after a premium smart-home control panel. The entire interface should appear to be molded from one warm light-gray material. Use a `#d9d9d9`-family page background and nearly identical card surfaces. Raised elements must use a soft white highlight toward the upper-left and a soft gray shadow toward the lower-right. Pressed controls must use the inverse inset version of the same lighting. Use large rounded corners, subtle depth, charcoal typography, thin line icons, generous whitespace, and minimal muted accent color. Avoid visible borders, pure white cards, black shadows, saturated gradients, glassmorphism, and flat Material-style components. Build reusable neumorphic primitives instead of styling each feature independently. Maintain accessible contrast, focus indicators, semantic controls, and responsive behavior.

---

# 34. Preferred Implementation Stack

For a React/Next.js project, preferred frontend stack:

```text
React / Next.js
TypeScript
CSS Modules, Tailwind CSS, or vanilla CSS
Inter
Lucide React
Framer Motion (optional)
```

Recommended visual dependencies:

```bash
npm install lucide-react @fontsource/inter
npm install framer-motion
```

The shadows, surfaces, radii, and pressed states should be built with normal CSS rather than a specialized neumorphism library.

---

# 35. Final Design Target

The completed frontend should feel:

```text
soft
physical
quiet
premium
monochrome
minimal
rounded
tactile
controlled
spacious
```

It should **not** feel:

```text
flat
corporate
high-contrast
glassy
neon
cartoonish
overly colorful
border-heavy
material-design-like
```

The visual benchmark is a premium appliance dashboard where every panel looks gently extruded from the same molded surface.
