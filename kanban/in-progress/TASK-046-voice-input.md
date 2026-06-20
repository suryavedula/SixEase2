# TASK-046: Voice input for query and dictation

**Status:** IN-PROGRESS · **Epic:** EPIC-11 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Add Web Speech (or STT service) input for both querying the canvas and dictating notes; push-to-talk UI in the dock; transcript shown before action.

## Acceptance Criteria
- [ ] voice query drives the command bar
- [ ] dictation captured to transcript
- [ ] graceful fallback when unsupported

## Dependencies
TASK-042 ✅ (InputDock.tsx is fully implemented — mic placeholder already present at line 191)

## Refs
Requirements §19.1 VN1

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- **Components:** `InputDock.tsx` — the exact dock this task extends; already has a `🎙` button stub (line 191-196) titled "Voice input (coming soon)" and a `/note` command stub (line 75-82) returning a FallbackCard with "Voice note (TASK-046 pending)". The `submit(text)` function at line 102 already accepts a text param — voice transcript feeds directly into it with no signature change.
- **State pattern:** `InputDock` uses simple `useState` hooks (`value`, `loading`, `hidden`). Voice state (`recording`, `transcript`, `supported`) will follow the same pattern via a custom hook.
- **Services:** `postOrchestrate` (api/orchestrate.ts) — existing NL query endpoint; transcript routes through it unchanged.
- **APIs:** No new endpoints needed. Web Speech API runs entirely in the browser. Transcript is a string that feeds `submit()` identically to keyboard input.
- **Database:** None — transcripts are transient; not persisted.
- **Utilities:** None needed beyond the hook itself.

### Dependencies Required
- **Frontend packages:** None. Web Speech API is browser-native (`SpeechRecognition` / `webkitSpeechRecognition`). No npm install required.
- **Backend packages:** None. No server-side STT — purely browser-side.
- **Database migrations:** None.
- **Docker services:** None.

### Impact Assessment

#### Files to Modify
- `frontend/src/components/shell/InputDock.tsx` — wire `🎙` button to push-to-talk, add transcript preview band above the input row, integrate `useVoiceInput` hook, disable mic when unsupported.

#### New Files
- `frontend/src/hooks/useVoiceInput.ts` — encapsulates `SpeechRecognition` state machine: `supported`, `recording`, `transcript`, `start()`, `stop()`. Keeps the component clean; hook is independently testable.

#### Components Affected
- `InputDock` (HIGH) — primary change target; button wiring + transcript preview UI
- `AppShell` / `Canvas` / all other components (NONE) — voice submits through existing `submit()` path, invisible to them.

#### API Changes
- None. Voice transcript enters `postOrchestrate` via the existing `submit(text)` call.

#### Database Changes
- None.

### Implementation Notes

**Push-to-talk state machine:**
```
idle → [press mic] → recording (interim transcript shown live)
     → [release mic] → preview (transcript editable before send)
     → [confirm/Enter] → submit() → idle
     → [cancel/Esc] → idle
```

**Transcript preview:** a thin band between the quick-chips and the input row, only visible when `transcript` is non-empty. Shows the text and a "× dismiss" button. Matches the existing chip-row styling (`text-[12px]`, `text-muted`).

**Graceful fallback:** if `'SpeechRecognition' in window || 'webkitSpeechRecognition' in window` is false, the `🎙` button renders with `opacity-30 cursor-not-allowed` and a tooltip "Voice not supported in this browser."

**`/note` command:** the existing stub (line 75-82) should be replaced to: capture a free-form dictation transcript and display it in a `FallbackCard` (or later a `VoiceNoteWidget`) with the raw text. Drives the "dictation captured to transcript" AC.

### Implementation Checklist
- [ ] Create `frontend/src/hooks/useVoiceInput.ts` with state machine + `SpeechRecognition` wrapper
- [ ] Wire `🎙` button in `InputDock.tsx` to `start()`/`stop()` on mousedown/mouseup (push-to-talk)
- [ ] Show interim transcript live in transcript preview band (above input row, below chips)
- [ ] On stop: leave transcript in preview band; Enter/click send → `submit(transcript)`, Esc → clear
- [ ] Replace `/note` stub to deliver transcript as a `FallbackCard` message (dictation AC)
- [ ] Disable mic button with visual indicator when `!supported` (fallback AC)
- [ ] Manual test: Chrome (supported) + Firefox without speech API (fallback path)

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - Browser support gap: Chrome/Edge support Web Speech; Firefox does not (as of 2026). **Mitigation:** graceful fallback already in AC; mic button degrades to disabled state.
  - Microphone permission prompt blocks first use. **Mitigation:** prompt fires on first `start()` call — UX is acceptable; no pre-request needed.
  - Interim transcript flicker on long utterances. **Mitigation:** show interim results but only submit on final result (`event.results[i].isFinal`).

### Estimated Effort
- Original: M
- Adjusted: M (no change — zero new deps, one hook + one component edit, no backend work)
