/**
 * downloadExporter — browser implementation of the repository's `exporter`
 * hook. The VM layer stays free of DOM and `fs`: the repository hands the
 * serialized workspace to this host-supplied function, which saves it as a
 * file download named after the path chosen in the save-file dialog.
 */
export function downloadExporter(path: string, payload: string): Promise<void> {
  const blob = new Blob([payload], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    // A browser download has no directory: keep only the file name.
    anchor.download = path.split(/[\\/]/).pop() ?? path;
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    try {
      anchor.click();
    } finally {
      anchor.remove();
    }
  } finally {
    // Revoke after the click has queued the download.
    setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 0);
  }
  return Promise.resolve();
}
