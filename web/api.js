/**
 * The server, as a set of functions. Nothing here knows what a screen looks like.
 *
 * Every call either resolves with parsed JSON or rejects with an `Error` whose
 * message is the server's `detail` string, so a screen can show the reason
 * without having to unwrap anything. The detail strings are written to be read
 * by a person ("that song is no longer on disk"), not by a log.
 */

/** Raised for any non-2xx response. `status` is the HTTP code. */
export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `request failed (${status})`);
    this.status = status;
  }
}

/** Await a request and parse it, or reject with the server's own wording. */
async function json(request) {
  const response = await request;
  if (!response.ok) {
    let detail = '';
    try {
      const body = await response.json();
      detail = body.detail || '';
    } catch {
      // A non-JSON error body is not worth reporting; the status says enough.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json();
}

/** Check ffmpeg is present before offering to accept a file. */
export async function health() {
  const response = await fetch('/api/health');
  if (!response.ok) throw new ApiError(response.status, 'the server is not answering');
  return response.json();
}

/** Where the speech-model download is. Polled while it runs. */
export function modelStatus() {
  return json(fetch('/api/models/asr'));
}

/** Start the speech-model download. A no-op when the weights are already there. */
export function startModelDownload() {
  return json(fetch('/api/models/asr', { method: 'POST' }));
}

/**
 * Send a file to the server. Upload progress is reported by the browser, which
 * is the only way to show a percentage for a large file: fetch cannot.
 */
export function upload(file, onProgress) {
  const body = new FormData();
  body.append('file', file, file.name);
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('POST', '/api/upload');
    request.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress((100 * event.loaded) / event.total);
      }
    });
    request.addEventListener('load', () => {
      let parsed = null;
      try {
        parsed = JSON.parse(request.responseText);
      } catch {
        parsed = null;
      }
      if (request.status >= 200 && request.status < 300) {
        resolve(parsed);
        return;
      }
      reject(new ApiError(request.status, parsed?.detail || 'the upload was refused'));
    });
    request.addEventListener('error', () => reject(new ApiError(0, 'the upload failed')));
    request.send(body);
  });
}

/** Queue a censor job for an already-uploaded source path. */
export function startJob(options) {
  return json(
    fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options),
    }),
  );
}

export function getJob(id) {
  return json(fetch(`/api/jobs/${id}`));
}

export function getReview(id) {
  return json(fetch(`/api/jobs/${id}/review`));
}

/**
 * Confirm the review and render. The server does the render in this same call,
 * so there is no separate "render" button request to get wrong.
 */
export function postReview(id, payload) {
  return json(
    fetch(`/api/jobs/${id}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  );
}

export function clipUrl(id, kind, start, end) {
  const query = new URLSearchParams({ kind, start: String(start), end: String(end) });
  return `/api/jobs/${id}/clip?${query}`;
}

export function outputUrl(id) {
  return `/api/jobs/${id}/output`;
}

export function originalUrl(id) {
  return `/api/jobs/${id}/original`;
}

/**
 * Follow a job's progress. `onEvent` gets every server event; the returned
 * function closes the stream.
 *
 * EventSource rather than fetch: the server sends `text/event-stream` and closes
 * when the job is done, and EventSource reconnects on its own if the laptop goes
 * to sleep mid-render.
 */
export function followJob(id, onEvent) {
  const source = new EventSource(`/api/jobs/${id}/events`);
  source.onmessage = (event) => {
    let payload = null;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }
    onEvent(payload);
    if (payload.event === 'done' || payload.event === 'error') source.close();
  };
  source.onerror = () => {
    // A closed stream after the job finished is normal; only a failure while the
    // job is still running is worth reporting.
    if (source.readyState === EventSource.CLOSED) onEvent({ event: 'closed' });
  };
  return () => source.close();
}