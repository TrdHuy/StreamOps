const statusDot = document.querySelector("#status-dot");
const statusText = document.querySelector("#status-text");
const preview = document.querySelector("#preview");
const emptyState = document.querySelector("#empty-state");
const captureTime = document.querySelector("#capture-time");
const captureResolution = document.querySelector("#capture-resolution");
const captureButton = document.querySelector("#capture-button");
const errorMessage = document.querySelector("#error-message");

let currentImageUrl = null;
let hasCapture = false;

async function updateHealth() {
  try {
    const response = await fetch("/api/v1/health", { cache: "no-store" });
    if (!response.ok) throw new Error("Health check failed");
    const health = await response.json();
    statusDot.className = health.capture_ready ? "status-dot online" : "status-dot warning";
    statusText.textContent = health.capture_ready ? "Online" : "Online, capture unavailable";
  } catch {
    statusDot.className = "status-dot offline";
    statusText.textContent = "Offline";
  }
}

async function loadLatest(url = `/api/v1/screen/latest?v=${Date.now()}`) {
  const response = await fetch(url, { cache: "no-store" });
  if (response.status === 404) {
    if (!hasCapture) showEmptyState();
    return false;
  }
  if (!response.ok) throw new Error(await apiError(response));

  const blob = await response.blob();
  const nextUrl = URL.createObjectURL(blob);
  const loader = new Image();
  try {
    await new Promise((resolve, reject) => {
      loader.onload = resolve;
      loader.onerror = () => reject(new Error("The captured image could not be displayed."));
      loader.src = nextUrl;
    });
  } catch (error) {
    URL.revokeObjectURL(nextUrl);
    throw error;
  }

  const previousUrl = currentImageUrl;
  currentImageUrl = nextUrl;
  preview.src = nextUrl;
  preview.hidden = false;
  emptyState.hidden = true;
  hasCapture = true;
  captureButton.textContent = "Capture Again";
  captureTime.textContent = formatCaptureTime(response.headers.get("X-Captured-At"));
  captureResolution.textContent = formatResolution(response.headers);
  if (previousUrl) URL.revokeObjectURL(previousUrl);
  return true;
}

async function captureScreen() {
  setError("");
  captureButton.disabled = true;
  captureButton.textContent = "Capturing...";
  try {
    const response = await fetch("/api/v1/screen/capture", {
      method: "POST",
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await apiError(response));
    const result = await response.json();
    await loadLatest(result.latest_url);
  } catch (error) {
    setError(error.message || "Screen capture failed.");
  } finally {
    captureButton.disabled = false;
    captureButton.textContent = hasCapture ? "Capture Again" : "Capture Screen";
  }
}

function showEmptyState() {
  preview.hidden = true;
  emptyState.hidden = false;
  captureTime.textContent = "Waiting for first capture";
  captureResolution.textContent = "--";
}

function formatCaptureTime(value) {
  if (!value) return "Captured just now";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : `Captured ${date.toLocaleString()}`;
}

function formatResolution(headers) {
  const width = headers.get("X-Image-Width");
  const height = headers.get("X-Image-Height");
  return width && height ? `${width} x ${height}` : "--";
}

async function apiError(response) {
  try {
    const body = await response.json();
    return body.error?.message || `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

function setError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = !message;
}

captureButton.addEventListener("click", captureScreen);
updateHealth();
loadLatest().catch((error) => setError(error.message));
setInterval(updateHealth, 15000);
