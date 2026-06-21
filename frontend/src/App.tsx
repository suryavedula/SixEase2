import { ThemeProvider } from "./theme/ThemeProvider";
import { PrefsProvider } from "./prefs/PrefsProvider";
import { ToastProvider } from "./context/ToastProvider";
import { AppShell } from "./components/shell/AppShell";

// Root component (TASK-003). Wraps the shell in the theme provider; domain
// providers (data, orchestrator state) are added by their owning tasks.
export default function App() {
  return (
    <ThemeProvider>
      <PrefsProvider>
        <ToastProvider>
          <AppShell />
        </ToastProvider>
      </PrefsProvider>
    </ThemeProvider>
  );
}
