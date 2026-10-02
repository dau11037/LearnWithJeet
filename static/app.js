require.config({ paths: { vs: "https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.52.2/min/vs" } });
require(["vs/editor/editor.main"], function () {
  const source = document.getElementById("editor");
  const host = document.createElement("div");
  host.className = "monaco-editor-container";
  source.replaceWith(host);
  const editor = monaco.editor.create(host, {
    value: source.value,
    language: "python",
    theme: "vs-dark",
    fontSize: 14,
    fontFamily: "'DM Mono', monospace",
    minimap: { enabled: false },
    padding: { top: 20, bottom: 20 },
    automaticLayout: true,
    scrollBeyondLastLine: false,
    roundedSelection: false,
  });
  const button = document.getElementById("run-button");
  const output = document.getElementById("output");
  const badge = document.getElementById("result-badge");
  async function runCode() {
    button.disabled = true;
    button.textContent = "Running…";
    output.textContent = "Executing against hidden test cases…";
    output.className = "min-h-24 whitespace-pre-wrap px-5 pb-6 font-mono text-sm leading-6 text-slate-400";
    badge.className = "hidden";
    try {
      const response = await fetch("/run-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ problem_id: window.PROBLEM_ID, code: editor.getValue() }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Request failed.");
      output.textContent = result.output;
      badge.textContent = `${result.passed}/${result.total} passed`;
      badge.className = `rounded-full px-2.5 py-1 text-xs ${result.success ? "bg-neon/10 text-neon" : "bg-red-400/10 text-red-300"}`;
      output.className = `min-h-24 whitespace-pre-wrap px-5 pb-6 font-mono text-sm leading-6 ${result.success ? "text-neon" : "text-red-300"}`;
    } catch (error) {
      output.textContent = error.message;
      output.className = "min-h-24 whitespace-pre-wrap px-5 pb-6 font-mono text-sm leading-6 text-red-300";
    } finally {
      button.disabled = false;
      button.innerHTML = "Run code <span class='ml-1'>⌘↵</span>";
    }
  }
  button.addEventListener("click", runCode);
  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, runCode);
});
