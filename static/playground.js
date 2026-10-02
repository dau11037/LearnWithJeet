require.config({ paths: { vs: "https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.52.2/min/vs" } });
require(["vs/editor/editor.main"], function () {
  const source = document.getElementById("playground-editor");
  const initial = source.value;
  const host = document.createElement("div");
  host.className = "playground-editor";
  source.replaceWith(host);
  const editor = monaco.editor.create(host, {
    value: initial, language: "python", theme: "vs-dark", fontSize: 14,
    fontFamily: "'DM Mono', monospace", minimap: { enabled: false },
    padding: { top: 22, bottom: 22 }, automaticLayout: true, scrollBeyondLastLine: false,
  });
  const run = document.getElementById("run-playground");
  const reset = document.getElementById("reset-playground");
  const stdin = document.getElementById("playground-stdin");
  const output = document.getElementById("playground-output");
  const status = document.getElementById("playground-status");
  async function execute() {
    run.disabled = true; run.textContent = "Running…"; status.textContent = "Executing"; output.textContent = "Running your Python program…";
    try {
      const response = await fetch("/run-playground", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code: editor.getValue(), stdin: stdin.value}) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Unable to run code.");
      output.textContent = result.output; status.textContent = result.success ? "Finished" : "Failed";
      output.className = `mt-4 min-h-48 whitespace-pre-wrap font-mono text-sm leading-6 ${result.success ? "text-neon" : "text-red-300"}`;
    } catch (error) { output.textContent = error.message; status.textContent = "Error"; output.className = "mt-4 min-h-48 whitespace-pre-wrap font-mono text-sm leading-6 text-red-300"; }
    finally { run.disabled = false; run.innerHTML = "Run code <span class='ml-1'>⌘↵</span>"; }
  }
  run.addEventListener("click", execute);
  reset.addEventListener("click", () => { editor.setValue(initial); stdin.value = ""; output.textContent = "Run your code to see output here."; status.textContent = "Ready"; });
  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, execute);
});
