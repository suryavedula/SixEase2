import { useTheme } from "../../theme/ThemeProvider";

// Dark/light theme toggle (TASK-003, AC #2). Sun/moon glyph reflects the
// theme you'll switch TO, which is the common affordance.
export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      onClick={toggleTheme}
      title={`Switch to ${next} theme`}
      aria-label={`Switch to ${next} theme`}
      className="flex h-9 w-9 items-center justify-center rounded-[10px] border border-border bg-panel2 text-text transition-colors hover:border-blue"
    >
      {theme === "dark" ? "☀️" : "🌙"}
    </button>
  );
}
