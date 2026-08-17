const DEFAULT_BASE_URL = "http://localhost:5050";

const input = document.getElementById("baseUrl");
const saved = document.getElementById("saved");

chrome.storage.sync.get("dashboardBaseUrl", (data) => {
  input.value = data.dashboardBaseUrl || DEFAULT_BASE_URL;
});

document.getElementById("saveBtn").addEventListener("click", () => {
  const value = input.value.trim() || DEFAULT_BASE_URL;
  chrome.storage.sync.set({ dashboardBaseUrl: value }, () => {
    saved.textContent = "Saved.";
    setTimeout(() => (saved.textContent = ""), 1500);
  });
});
