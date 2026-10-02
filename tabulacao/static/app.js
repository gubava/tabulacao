let jobId = null;
let colunasDisponiveis = [];

const formUpload = document.getElementById("form-upload");
const camposArea = document.getElementById("campos-area");
const camposLista = document.getElementById("campos-lista");
const btnProcessar = document.getElementById("btn-processar");
const revisaoArea = document.getElementById("revisao-area");
const revisaoResumo = document.getElementById("revisao-resumo");
const paresLista = document.getElementById("pares-lista");
const btnFinalizar = document.getElementById("btn-finalizar");
const resultArea = document.getElementById("result-area");

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s == null ? "" : String(s);
  return div.innerHTML;
}

formUpload.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const dados = new FormData(formUpload);
  const resp = await fetch("/api/detectar-colunas", { method: "POST", body: dados });
  const json = await resp.json();
  if (!resp.ok) { alert(json.erro); return; }
  jobId = json.job_id;
  colunasDisponiveis = json.colunas_disponiveis;
  mostrarCampos(json.campos);
});

function mostrarCampos(campos) {
  camposLista.innerHTML = campos.map((c) => `
    <div class="campo-row">
      <label class="campo-label ${c.identificado ? "" : "nao-identificado"}">
        ${escapeHtml(c.campo)}${c.identificado ? "" : " (não identificado)"}
      </label>
      <select data-campo="${c.campo}">
        <option value="">(nenhuma)</option>
        ${colunasDisponiveis.map((col) => `
          <option value="${escapeHtml(col)}" ${col === c.coluna_detectada ? "selected" : ""}>${escapeHtml(col)}</option>
        `).join("")}
      </select>
    </div>
  `).join("");
  camposArea.classList.remove("hidden");
}

btnProcessar.addEventListener("click", async () => {
  const mapeamento = {};
  camposLista.querySelectorAll("select[data-campo]").forEach((sel) => {
    mapeamento[sel.dataset.campo] = sel.value;
  });

  const resp = await fetch("/api/processar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_id: jobId, mapeamento }),
  });
  const json = await resp.json();
  if (!resp.ok) { alert(json.erro); return; }

  if (json.pares_possiveis.length > 0) {
    mostrarRevisao(json);
  } else {
    await finalizar({});
  }
});

function mostrarRevisao(json) {
  camposArea.classList.add("hidden");
  revisaoResumo.textContent =
    `${json.registros_encontrados} registro(s) · ${json.duplicidades_confirmadas} confirmada(s) já removida(s) · ` +
    `${json.pares_possiveis.length} possível(is) para você revisar`;

  paresLista.innerHTML = json.pares_possiveis.map((par, i) => `
    <div class="par-card" data-key="${par.key}">
      <div class="par-motivo">${escapeHtml(par.motivo)}${par.similaridade < 100 ? ` (${par.similaridade}% parecido)` : ""}</div>
      <div class="par-registros">
        <div class="par-registro">
          <strong>${escapeHtml(par.registro_a.nome)}</strong><br>
          CPF: ${escapeHtml(par.registro_a.cpf) || "—"}<br>
          Nascimento: ${escapeHtml(par.registro_a.nascimento) || "—"}
        </div>
        <div class="par-registro">
          <strong>${escapeHtml(par.registro_b.nome)}</strong><br>
          CPF: ${escapeHtml(par.registro_b.cpf) || "—"}<br>
          Nascimento: ${escapeHtml(par.registro_b.nascimento) || "—"}
        </div>
      </div>
      <div class="par-acoes">
        <label><input type="radio" name="par-${i}" value="manter_ambos" checked> Manter os dois</label>
        <label><input type="radio" name="par-${i}" value="manter_1"> Manter só o 1º</label>
        <label><input type="radio" name="par-${i}" value="manter_2"> Manter só o 2º</label>
        <label><input type="radio" name="par-${i}" value="excluir"> Excluir os dois</label>
      </div>
    </div>
  `).join("");
  revisaoArea.classList.remove("hidden");
}

btnFinalizar.addEventListener("click", async () => {
  const decisoes = {};
  paresLista.querySelectorAll(".par-card").forEach((card) => {
    const key = card.dataset.key;
    const selecionado = card.querySelector("input:checked");
    decisoes[key] = selecionado ? selecionado.value : "manter_ambos";
  });
  await finalizar(decisoes);
});

async function finalizar(decisoes) {
  // Antes, se o servidor travasse com um erro ou ficasse fora do ar,
  // essa função falhava caladinha (sem try/catch nenhum) — o clique no
  // botão "parecia" não fazer nada, sem nenhuma mensagem. Agora todo
  // erro (de rede, do servidor, ou qualquer outro) aparece visível na
  // tela, nunca mais some em silêncio.
  btnFinalizar.disabled = true;
  btnFinalizar.textContent = "Gerando arquivo...";
  try {
    const resp = await fetch("/api/finalizar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId, decisoes }),
    });

    let json;
    try {
      json = await resp.json();
    } catch (erroJson) {
      throw new Error(
        `O servidor respondeu algo que não é JSON (status ${resp.status}). ` +
        "Veja o terminal onde o 'py app.py' está rodando para o erro completo."
      );
    }

    if (!resp.ok) {
      throw new Error(json.erro || `Erro desconhecido (status ${resp.status}).`);
    }

    revisaoArea.classList.add("hidden");
    resultArea.innerHTML = `
      <h2>Base tratada com sucesso.</h2>
      <p><strong>Vidas finais:</strong> ${json.vidas_finais}</p>
      <a class="btn-download" href="${json.download_url}">Baixar arquivo</a>
    `;
    resultArea.classList.remove("hidden");
  } catch (erro) {
    resultArea.innerHTML = `
      <h2 style="color:#C0392B">Não foi possível gerar o arquivo.</h2>
      <p>${erro.message}</p>
    `;
    resultArea.classList.remove("hidden");
    resultArea.scrollIntoView({ behavior: "smooth" });
  } finally {
    btnFinalizar.disabled = false;
    btnFinalizar.textContent = "Confirmar e Gerar Arquivo";
  }
}
