import type { UploadTarget } from "@jps/api-client";

/**
 * Send a file straight to storage with the signed URL the API issued.
 * XMLHttpRequest is used because fetch cannot report upload progress.
 */
export function sendToStorage(
  target: UploadTarget,
  file: File,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open(target.method, target.url);
    for (const [name, value] of Object.entries(target.headers)) {
      request.setRequestHeader(name, value);
    }
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        onProgress(1);
        resolve();
      } else {
        reject(new Error(`The upload failed (HTTP ${request.status}). Try again.`));
      }
    };
    request.onerror = () =>
      reject(new Error("The upload was interrupted. Check your connection and try again."));
    request.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
    signal?.addEventListener("abort", () => request.abort());
    request.send(file);
  });
}
