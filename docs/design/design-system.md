# Front Desk design system

The staff dashboard (`apps/web`) is used by receptionists and one admin at a clinic front desk: a lit room, a desktop or tablet screen that patients standing at the counter can see, frequent interruptions. The design follows from that:

- **Legible first.** One typeface chosen for telling look-alike characters apart, because staff read phone numbers and `APT-000123` references aloud.
- **Calm by default, unmistakable when it matters.** The page is quiet greys and a deep pine; colour is spent on state. An emergency alert is clearly different without flashing, sirens or alarm wording that would frighten a patient reading over the counter.
- **Forgiving.** Anything that removes an item from a list or cannot be undone asks first, keeps what the user typed when something fails, and says what to do next.

Tokens live in [`apps/web/app/globals.css`](../../apps/web/app/globals.css) as CSS variables and are exposed to Tailwind v4 through `@theme inline` (`bg-status-attention-bg`, `text-display`, `shadow-[var(--shadow-panel)]`, …). Components never use raw hex values.

## Colour

Light theme only. Reception desks are brightly lit, and one theme halves the contrast surface to verify; a dark palette can be added later as its own validated set (the `dark` variant is kept so the copied shadcn components compile).

| Token | Value | Use |
|---|---|---|
| `--background` | `#f3f5f4` | Page (cool grey with a hint of green) |
| `--card`, `--popover` | `#ffffff` | Panels, rows, dialogs |
| `--foreground` | `#17211e` | Body text, headings |
| `--muted-foreground` | `#4f5d58` | Secondary text, hints |
| `--border` | `#d5deda` | Dividers, panel outlines (decorative) |
| `--input` | `#7d8c86` | Form-control borders (3.52:1 on white, meets the 3:1 non-text rule) |
| `--primary` / `--primary-foreground` | `#1d5c4e` / `#ffffff` | Pine: primary buttons, current nav item, focus |
| `--primary-soft` | `#e3efeb` | Selected nav item, hover on choices |
| `--ring` | `#2d7a68` | Focus ring (5.13:1 on white) |
| `--destructive` | `#b3261e` | Destructive buttons and error edges |

### Status semantics

Each state has a text colour, a tint and an edge. **A state is always shown as text plus an icon; colour is the third, redundant cue.**

| State | Text / tint / edge | Label and icon | Where |
|---|---|---|---|
| booked | `#1d5c4e` / `#e3efeb` / `#2d7a68` | "Booked", calendar-clock | Normal upcoming appointment; shares the brand colour because it is the normal case |
| completed | `#3c4a45` / `#eceeed` / `#7d8c86` | "Completed", check | Recedes: finished work should not compete with what is coming |
| cancelled | `#56635e` / `#f1f3f2` / `#9aa6a1` | "Cancelled", circle-x; the time is struck through | Kept in the list for context, visually quiet |
| no_show | `#8a4b08` / `#fbf0e1` / `#b4630f` | "No-show", user-x | Amber-brown, distinct from attention |
| attention | `#7a4d00` / `#fff4d6` / `#b07d00` | "Needs a call", phone | Staff must call the patient (failed notice, help request) |
| emergency | `#8e1b1b` / `#fcebea` / `#b42318` | "Emergency message: contact the patient now", heart-pulse | Always first in the attention panel |

The emergency treatment is a deep crimson edge and a pale tint with normal-weight body text. It does not flash, pulse or play sound, and it uses no siren icon or capitals: unmistakable to staff, unremarkable to a patient glancing at the screen.

Contrast (WCAG 2.x relative luminance, computed for every pair): ink on white 16.5:1, muted on page 6.31:1, white on pine 7.8:1; status text on its tint is between 5.64:1 (cancelled) and 8.04:1 (completed). All text pairs meet AA (4.5:1). Status edges are redundant cues next to text, so the 3:1 non-text rule does not apply to them alone; the cancelled edge (2.52:1) is deliberately faint.

## Typography

**Atkinson Hyperlegible Next** (variable 200–800, latin + latin-ext, self-hosted by `next/font`), falling back to the system UI font. It was designed for low-vision readers and separates 0/O and 1/l/I, which matters for phone numbers and references. One family for everything; hierarchy comes from size and weight. Times, counts and references use tabular figures (`time`, `.tabular`).

| Token | Size / line height | Use |
|---|---|---|
| `text-caption` | 13 px / 1.35 | References, timestamps, helper text (never smaller) |
| `text-body-sm` | 15 px / 1.45 | Dense rows, secondary lines |
| base | 16 px / 1.5 | Body and every form control (no shrinking on desktop) |
| `text-title` | 18 px / 1.3 | Section and doctor headings |
| `text-heading` | 22 px / 1.25 | Dialog-level headings |
| `text-display` | 28 px / 1.2 | Page titles, stat values |
| `text-slot` | 20 px / 1.1, bold | Appointment times in the day list (the signature element) |

## Spacing, radius, elevation

- **Spacing:** Tailwind's 4 px scale. Rows use 12–16 px padding, panels 16–20 px, sections 24 px apart.
- **Radius:** `--radius: 0.5rem`. Controls `radius-md` (6.4 px), rows and panels `radius-lg`/`radius-xl` (8–11 px), pills fully rounded. Hierarchy, not one radius everywhere.
- **Elevation:** surfaces are flat and separated by borders. `--shadow-panel` (1–2 px, 6% ink) for schedule panels; `--shadow-overlay` (12/32 px, 18% ink) only for things that float: dialogs, toasts, the sticky save bar.
- **Touch targets:** controls are 40 px high by default, 44 px for large buttons, slot choices and nav items.

## Layout

- ≥ 1024 px: fixed 16 rem sidebar (Today, Book appointment; admin group only for admins) and a content column up to 72 rem.
- < 1024 px (tablet): top bar with the brand and a menu button that opens the navigation in a sheet.
- **Day list:** one panel per doctor; each appointment is a row with a 4 px status edge on the left, the time large on the left, patient and badges in the middle, one "Actions" menu on the right. On tablets the actions wrap under the details.
- Attention panel sits above the schedule whenever something is open; otherwise a one-line "Nothing needs attention right now."

## Components and usage rules

| Need | Use | Rule |
|---|---|---|
| Destructive or irreversible action | `ConfirmDialog` (shadcn `AlertDialog`) | Names the patient/time, says the consequence, keeps the dialog open on failure with the error inline. Cancel buttons say what they keep ("Keep appointment"). |
| Create/edit forms | shadcn `Dialog` + `Field` | Visible labels, error under the field (`role="alert"`), helper text for formats, "Close without saving". |
| Row actions | `DropdownMenu` (non-modal) | Disabled items explain why in a menu label (e.g. attendance before start time). |
| Status | `StatusPill`, `SourcePill`, `ReminderPill`, `AttentionPill` | Icon + text, never colour alone. |
| Loading | `LoadingState` (skeletons, `role="status"`) | Same shape as the content; no spinners for whole sections. |
| Empty | `EmptyState` | Says what the empty state means and offers the next step. |
| Error | `ErrorState` / `InlineError` | API message, "Try again", and the request id as "Support reference". 403 uses `ForbiddenState`. |
| Feedback | `useToast()` | Success toasts are polite and dismiss after 6 s; error toasts are assertive and stay 12 s. The action keeps its name ("Cancel appointment" → "Appointment cancelled"). |
| Dates | `formatLongDate`, `formatShortDate` | Calendar dates from the API; appointment times always from `time_label`. UTC instants are shown as "x minutes ago" with the UTC time on hover, or explicitly in UTC (activity log). The browser never converts clinic time. |

## Accessibility rules

- WCAG 2.2 AA contrast for all text; 3:1 for input borders and focus rings.
- Focus is always visible: a 3 px opaque `--ring` on every interactive element (shadcn's 50% ring was made opaque).
- Status, validation and errors are never colour-only: text and icons always accompany them.
- Every input has a `<label>`; errors are linked with `aria-describedby`/`aria-invalid`; grouped choices (slots, patients) are native radio inputs in a `fieldset` with a `legend`.
- Live updates: toasts and loading states use `role="status"`/`aria-live`; errors use `role="alert"`.
- Skip link to the main content; one `h1` per page; sections are labelled by their headings.
- Reduced motion: animations and transitions are cut to near zero under `prefers-reduced-motion`.
- No patient data in the console, page titles or URLs other than the exact-phone lookup request.
