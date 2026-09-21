"use client";

import { type ChangeEvent, type DragEvent, type KeyboardEvent, type RefObject } from "react";
import { Mic, Paperclip, Send, Square, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { PendingAttachment } from "./types";

export function ChatComposer({
  draft,
  attachments,
  sending,
  micRecording,
  sttProvider,
  textareaRef,
  fileRef,
  mentionList,
  controls,
  onDraftChange,
  onCursorChange,
  onKeyDown,
  onFiles,
  onRemoveAttachment,
  onToggleMic,
  onSend,
  onCancel,
  footerMeta,
}: {
  draft: string;
  attachments: PendingAttachment[];
  sending: boolean;
  micRecording: boolean;
  sttProvider: "none" | "voicestudio" | "paste";
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  fileRef: RefObject<HTMLInputElement | null>;
  mentionList?: React.ReactNode;
  controls?: React.ReactNode;
  footerMeta?: React.ReactNode;
  onDraftChange: (value: string, cursor: number) => void;
  onCursorChange: (cursor: number) => void;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onFiles: (files: File[]) => void;
  onRemoveAttachment: (id: string) => void;
  onToggleMic: () => void;
  onSend: () => void;
  onCancel?: () => void;
}) {
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    onFiles(Array.from(event.dataTransfer.files || []));
  };

  return (
    <>
      {attachments.length ? (
        <div className="pending-attachments">
          {attachments.map((item) => (
            <span key={item.artifact_id} className="pending-attachment">
              {item.filename}
              <button type="button" aria-label={`Bijlage ${item.filename} verwijderen`} onClick={() => onRemoveAttachment(item.artifact_id)}><X /></button>
            </span>
          ))}
        </div>
      ) : null}
      <div className="composer composer-with-mentions" onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
        <div className="composer-input-wrap">
          <Textarea
            ref={textareaRef}
            value={draft}
            onChange={(event) => onDraftChange(event.target.value, event.target.selectionStart ?? event.target.value.length)}
            onSelect={(event) => onCursorChange(event.currentTarget.selectionStart ?? 0)}
            onClick={(event) => onCursorChange(event.currentTarget.selectionStart ?? 0)}
            onKeyUp={(event) => onCursorChange(event.currentTarget.selectionStart ?? 0)}
            onKeyDown={onKeyDown}
            onPaste={(event) => {
              const files = Array.from(event.clipboardData?.files || []).filter((file) => file.type.startsWith("image/"));
              if (!files.length) return;
              event.preventDefault();
              onFiles(files);
            }}
            aria-label="Bericht"
            placeholder="Vraag stellen, /help, /harvest <url>, @memory:… of sleep bestanden…"
            disabled={sending}
          />
          {mentionList}
        </div>
        <div className="composer-toolbar">
          <div>
            <input
              ref={fileRef}
              className="visually-hidden"
              type="file"
              multiple
              onChange={(event: ChangeEvent<HTMLInputElement>) => {
                onFiles(Array.from(event.target.files || []));
                event.target.value = "";
              }}
            />
            <Button variant="ghost" size="sm" onClick={() => fileRef.current?.click()} disabled={sending}><Paperclip />Bijlage</Button>
            <Button
              variant={micRecording ? "outline" : "ghost"}
              size="sm"
              onClick={onToggleMic}
              disabled={sending}
              aria-label={micRecording ? "Opname stoppen" : "Microfoon"}
              title={sttProvider === "voicestudio" ? "Lokale VoiceStudio-STT" : "STT apart configureerbaar onder Instellingen → Spraak"}
            >
              <Mic />{micRecording ? "Stop mic" : "Mic"}
            </Button>
            <span className="token-estimate">/help · /harvest · @memory · @codebase · Enter verstuurt</span>
          </div>
          {sending ? (
            <Button className="send-button" size="icon" onClick={onCancel} disabled={!onCancel} aria-label="Generatie annuleren">
              <Square />
            </Button>
          ) : (
            <Button className="send-button" size="icon" onClick={onSend} disabled={!draft.trim() && !attachments.length} aria-label="Bericht versturen">
              <Send />
            </Button>
          )}
        </div>
        {controls}
      </div>
      <p className="composer-footnote">
        {footerMeta || "Modeluitvoer kan fouten bevatten. Pins en @ brengen context — niet de volledige bron in elke prompt."}
      </p>
    </>
  );
}
