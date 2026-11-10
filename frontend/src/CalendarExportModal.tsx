import { useEffect, useRef, useState } from "react";
import { downloadCalendar } from "./api";

export default function CalendarExportModal({ onClose }: { onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const [error, setError] = useState("");
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    closeButton.current?.focus();
    const handleKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", handleKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement) previousFocus.focus();
    };
  }, [onClose]);

  async function handleDownload() {
    setBusy(true);
    setError("");
    try {
      await downloadCalendar();
      setDownloaded(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not export calendar.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="modal calendar-export-dialog" role="dialog" aria-modal="true" aria-labelledby="calendar-export-title">
        <div className="modal-header">
          <div><p className="eyebrow">Keep dates within reach</p><h2 id="calendar-export-title">Export to your calendar</h2></div>
          <button ref={closeButton} className="icon-button" onClick={onClose} aria-label="Close calendar export">×</button>
        </div>
        <p>Download an .ics file to import into Google Calendar, Outlook, or Apple Calendar.</p>
        <ul className="calendar-export-details">
          <li>Includes all dated deadlines and next steps for Saved, Applied, Interview, and Offer applications, including past dates.</li>
          <li>Dates become all-day events. Your current table filters do not limit the export.</li>
          <li>The file contains company names, roles, dates, and next-step text. Private notes and connected email data are excluded.</li>
        </ul>
        <p>This is a one-time snapshot. Changes in InternTrack will not update imported events. Use a separate calendar you can replace when importing a newer snapshot; repeated imports may create duplicates.</p>
        {downloaded && <p className="form-success" role="status">Calendar file downloaded. Import it using your calendar app’s file import option.</p>}
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="button secondary" onClick={onClose}>Close</button>
          <button type="button" className="button primary" disabled={busy} onClick={() => void handleDownload()}>{busy ? "Exporting…" : "Download .ics"}</button>
        </div>
      </section>
    </div>
  );
}

