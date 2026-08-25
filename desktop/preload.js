// Preload bridge reserved for future native folder pickers.
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("turnwiseDesktop", {
  isDesktop: true,
  platform: process.platform,
});
