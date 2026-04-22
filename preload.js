const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("petAPI", {
  onStateChange: (callback) => {
    ipcRenderer.on("state-change", (_event, state) => callback(state));
  },
  setIgnoreMouseEvents: (ignore) => {
    ipcRenderer.send("set-ignore-mouse-events", ignore);
  },
  moveWindow: (dx, dy) => {
    ipcRenderer.send("window-move", dx, dy);
  },
});