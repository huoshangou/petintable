#!/usr/bin/env node

const { spawn } = require("child_process");
const path = require("path");
const electron = require("electron");

const appRoot = path.resolve(__dirname, "..");

const child = spawn(electron, [appRoot], {
  stdio: "inherit",
  env: { ...process.env },
});

child.on("close", (code) => {
  process.exit(code || 0);
});