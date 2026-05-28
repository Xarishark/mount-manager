# GNOME HIG audit — SMB Mount Manager

Date: 2026-05-28
Scope: Full sweep of the libadwaita UI on branch `feat/libadwaita-01`.
Reference: https://developer.gnome.org/hig/index.html

Findings are organized by severity. Each cites the HIG page it draws from so it
can be split into individual GitHub issues without losing context.

---

## Critical

*(None.)* The app respects the big architectural HIG choices: `AdwApplicationWindow`
+ `AdwToolbarView` + `AdwToastOverlay`, hybrid `AdwActionRow` pattern,
`AdwStatusPage` empty state, `AdwAlertDialog` for destructive confirmation,
`AdwAboutDialog` with proper metadata, color scheme delegated to
`Adw.StyleManager`.

---

## Major

### M1. No keyboard shortcuts at all

**HIG:** `guidelines/keyboard.html`, `reference/keyboard.html`

Every common action should be keyboard-reachable and standard accelerators
should be wired up. Currently the app has zero accelerators.

Missing, at minimum:

- `Ctrl+W` — close window
- `Ctrl+Q` — quit
- `Ctrl+N` — Add Share (closest standard mapping for "create new item")
- `Ctrl+R` — refresh
- `F10` — primary menu
- `Ctrl+?` — Keyboard Shortcuts dialog

And the supporting UI:

- A `Gtk.ShortcutsWindow` describing the above.
- A "Keyboard Shortcuts" entry in the primary menu.

Also: when the AddShareDialog opens, no widget has explicit initial focus
(see m5).

### M2. Suggested-action label-only button in a primary-window header bar

**HIG:** `patterns/containers/header-bars.html` → Button Style

> Types of buttons which don't automatically have their appearance adjusted
> when in a header bar include buttons with: a text label only;
> the suggested and destructive action styles … These button types should
> generally be avoided for primary window header bars, since it leads to a
> complex and inconsistent visual appearance.

The header-bar "Add Share" button has both attributes. Fix:

- Add an icon (e.g. `list-add-symbolic`) so the button is icon+label.
- Drop the `suggested-action` CSS class on the header copy.
- Keep the empty-state pill button as the lone suggested-action CTA.

### M3. Two suggested-action buttons visible simultaneously in the empty state

**HIG:** `patterns/controls/buttons.html` → Suggested & Destructive Actions

> Each view should only ever include a single button using either the
> suggested or destructive styles.

In the empty state, both the header-bar "Add Share" and the pill "Add Share"
on the `AdwStatusPage` carry `suggested-action`. Fixing M2 (drop suggested
from the header button) also fixes this.

---

## Minor

### m1. Toast titles end with periods

**HIG:** `guidelines/writing-style.html` → Periods; `patterns/feedback/toasts.html` →
toasts use the informal heading style.

> Text generally shouldn't end with a period.

Affected strings in `mount_manager_ui.py`:

- `f"{share} added."`
- `f"{record.source} removed."`
- `f"{record.source} upgraded."`
- All `f"… failed: {exc}"` toasts and the "Mount folder does not exist: …" toast.

Drop the trailing period from every toast title.

### m2. Empty-state description uses Pango italics

`empty_page.set_description("Click <i>Add Share</i> to mount one.")` renders the
button name in italics. Italic emphasis is not an HIG pattern for
`AdwStatusPage` descriptions. Use plain text:

> `Click "Add Share" to mount one`

(Note: also drop the trailing period per m1.)

### m3. Header-bar "Add Share" tooltip duplicates the label

**HIG:** Tooltips should add information, not echo the label.

Current: button label `"Add Share"`, tooltip `"Add share"`. Either remove the
tooltip or change it to add value — e.g. `"Mount a new SMB share"`.

### m4. Primary menu tooltip says "Main menu"

**HIG:** standard terminology is "Primary menu." Change the
`open-menu-symbolic` `MenuButton` tooltip from `"Main menu"` to
`"Primary menu"`.

### m5. AddShareDialog does not set a default widget / initial focus

**HIG:** `patterns/feedback/dialogs.html`

> Assign the return key to activate the affirmative button. However, this
> should not be done if its action is irreversible, destructive or otherwise
> inconvenient to the user.
> When opening a dialog, provide initial keyboard focus to the component that
> you expect users to operate first.

Currently neither is done. Add:

- `self.set_default_widget(self.add_button)` so Enter in the password field
  submits.
- Explicit focus on `self.path_row` when the dialog presents.

### m6. AlertDialog affirmative button labelled "Delete"

**HIG:** `patterns/feedback/dialogs.html`

> Label the affirmative button with a specific imperative verb.

Borderline — the dialog heading ("Delete this SMB mount?") carries the object.
`"Delete Share"` or `"Remove Mount"` is more in line with the guideline. Low
priority; mention if revisiting that dialog.

### m7. Mount group title `"SMB Shares"` duplicates the window title context

The window is already "SMB Mount Manager." Single-group preferences pages
typically omit the group title, or use a neutral one. Consider dropping it or
renaming to `"Mounts"`.

---

## Nits

### n1. Legacy icon names

`emblem-ok-symbolic` → `checkmark-symbolic`
`dialog-error-symbolic` → `error-symbolic`

Both legacy names still resolve; the new names are more idiomatic in fresh
GTK4 / libadwaita code.

### n2. Empty-state icon

`folder-remote-symbolic` is fine but `network-server-symbolic` is arguably a
better match for SMB. Subjective.

### n3. Redundant calls in AddShareDialog header

`self._header.set_show_start_title_buttons(False)` and
`set_show_end_title_buttons(False)` are redundant — `AdwDialog` already manages
its title-bar buttons.

### n4. About dialog has overlapping developer fields

`AdwAboutDialog` is constructed with both
`developer_name=APP_DEVELOPERS[0]` and then `set_developers(APP_DEVELOPERS)`.
Both end up populated; pick one form per role (`developer_name` is the
single-line credit, `developers` is the list shown on the credits page).

---

## Intentionally non-compliant (justified)

### Destructive Delete uses confirmation, not undo

**HIG:** `patterns/feedback/dialogs.html` → Confirmation Dialogs

> Undo is typically a better option than a confirmation dialog.

Undoing delete here would require re-creating the systemd units and
re-decrypting credentials — non-trivial. Confirmation is the right call. Worth
being explicit in the code so future contributors understand why this path was
chosen.

---

## Strengths (for completeness)

- `AdwApplicationWindow` + `AdwToolbarView` + `AdwToastOverlay` shell.
- Hybrid `AdwActionRow` pattern (switch + single inline suffix + kebab menu).
- `AdwStatusPage` empty state with a clear primary CTA.
- `AdwAlertDialog` with `DESTRUCTIVE` response appearance, `cancel` set as both
  default and close response.
- `AdwAboutDialog` with developers, website, issue URL, license type.
- Color scheme delegated to `Adw.StyleManager.ColorScheme.DEFAULT` (respects
  system preference; no custom CSS).
- Debounced host check with `Gio.Cancellable` and explicit `GLib.source_remove`
  on dialog close — no race between debounce, worker thread, and dialog
  teardown.
- All user-controlled strings escaped with `GLib.markup_escape_text` before
  being rendered as Pango markup.

---

## Suggested ordering when filing issues

1. M1 — keyboard shortcuts + shortcuts window (largest accessibility gap)
2. M2 + M3 — header-bar Add Share style (small fix, fixes both)
3. m1 — toast period sweep
4. m2 — empty-state description
5. m3 + m4 — tooltip copy
6. m5 — AddShareDialog default widget + initial focus
7. m6, m7 — copy refinements
8. n1–n4 — opportunistic cleanups
