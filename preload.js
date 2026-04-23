const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("petAPI", {
  onStateChange: (callback) => {
    ipcRenderer.on("state-change", (_event, state) => callback(state));
  },
  onSkinChange: (callback) => {
    ipcRenderer.on("skin-change", (_event, skin) => callback(skin));
  },
  getCurrentSkin: () => ipcRenderer.invoke("get-current-skin"),
  setIgnoreMouseEvents: (ignore) => {
    ipcRenderer.send("set-ignore-mouse-events", ignore);
  },
  moveWindow: (dx, dy) => {
    ipcRenderer.send("window-move", dx, dy);
  },
  showContextMenu: () => ipcRenderer.send("show-context-menu"),
});
