// Conversation bubble (TASK-043). Renders a single chat turn inside the canvas
// so the generative-UI views and the dialogue share one scroll surface.

interface ChatMessageProps {
  role?: "user" | "assistant";
  text?: string;
  pending?: boolean;
}

export function ChatMessage({ role = "assistant", text = "", pending = false }: ChatMessageProps) {
  const isUser = role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-blue/15 px-3.5 py-2 text-[13.5px] leading-relaxed text-text">
          {text}
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-2.5">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-border bg-panel2 text-[13px] text-blue">
        ◆
      </div>
      <div className="max-w-[80%] rounded-2xl rounded-tl-sm bg-panel px-3.5 py-2 text-[13.5px] leading-relaxed text-text">
        {pending ? (
          <span className="inline-flex gap-1 py-1" aria-label="Thinking">
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-dim [animation-delay:-0.3s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-dim [animation-delay:-0.15s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-dim" />
          </span>
        ) : (
          <span className="whitespace-pre-wrap">{text}</span>
        )}
      </div>
    </div>
  );
}
