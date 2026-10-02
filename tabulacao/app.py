"""
app.py
-------
Recebe pedidos do navegador e chama a engine (pasta src/tabulacao).

O modelo de tabulação (modelos/Modelo_de_Estudo.xlsx) já vem embutido
no projeto — a pessoa só precisa enviar a base de vidas, não precisa
anexar o modelo toda vez.

Fluxo em 3 etapas:
    1. /api/detectar-colunas  -> lê o cabeçalho da base, devolve mapeamento
    2. /api/processar          -> trata os dados, acha duplicidades
    3. /api/finalizar          -> aplica decisões, gera o arquivo final
                                   preenchendo o modelo real

Para rodar:
    pip install -r requirements.txt
    python app.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, abort

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from tabulacao import pipeline, excel_writer  # noqa: E402

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024

WORK_DIR = Path(tempfile.gettempdir()) / "tabulacao_web"
WORK_DIR.mkdir(parents=True, exist_ok=True)

# Modelo de tabulação embutido no projeto — a pessoa não precisa anexar
# esse arquivo, ele já vem pronto dentro da pasta modelos/
MODELO_PADRAO = PROJECT_ROOT / "modelos" / "Modelo_de_Estudo.xlsx"

_jobs: dict[str, dict] = {}


def _safe_filename(name: str) -> str:
    keep = "-_. "
    return "".join(c for c in name if c.isalnum() or c in keep).strip() or "arquivo"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/detectar-colunas", methods=["POST"])
def detectar_colunas():
    arquivos = request.files.getlist("bases")
    if not arquivos or not any(f.filename for f in arquivos):
        return jsonify({"erro": "Nenhum arquivo enviado."}), 400

    if not MODELO_PADRAO.exists():
        return jsonify({"erro": "Modelo de tabulação não encontrado no servidor (modelos/Modelo_de_Estudo.xlsx)."}), 500

    job_id = uuid.uuid4().hex
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True)

    caminhos = []
    for f in arquivos:
        if not f.filename:
            continue
        p = job_dir / _safe_filename(f.filename)
        f.save(p)
        caminhos.append(str(p))

    try:
        colunas, mapeamento = pipeline.detect_columns(caminhos)
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"erro": f"Não foi possível ler o arquivo: {e}"}), 400

    _jobs[job_id] = {"job_dir": job_dir, "source_paths": caminhos}

    campos = [
        {"campo": campo, "coluna_detectada": mapeamento.mapping.get(campo),
         "identificado": campo in mapeamento.mapping}
        for campo in ["nome", "cpf", "nascimento", "sexo", "matricula", "parentesco", "tda", "plano", "mensalidade"]
    ]

    return jsonify({"job_id": job_id, "colunas_disponiveis": colunas, "campos": campos})


@app.route("/api/processar", methods=["POST"])
def processar():
    payload = request.get_json(silent=True) or {}
    job_id = payload.get("job_id", "")
    mapeamento_manual = {k: v for k, v in (payload.get("mapeamento") or {}).items() if v}

    job = _jobs.get(job_id)
    if not job:
        return jsonify({"erro": "Sessão expirada — envie os arquivos novamente."}), 404

    try:
        resultado = pipeline.process_sources(job["source_paths"], manual_overrides=mapeamento_manual)
        job["process_result"] = resultado

        df = resultado.df_clean
        pares_possiveis = []
        for par in resultado.dedup.pairs:
            if par.status.value != "possivel":
                continue
            row_a, row_b = df.loc[par.index_a], df.loc[par.index_b]
            pares_possiveis.append({
                "key": f"{par.index_a}-{par.index_b}",
                "motivo": par.reason.value,
                "similaridade": round(par.similarity, 1),
                "registro_a": {"nome": row_a.get("_nome") or "", "cpf": row_a.get("_cpf") or "",
                                "matricula": row_a.get("_matricula") or "", "nascimento": str(row_a.get("_nascimento") or "")},
                "registro_b": {"nome": row_b.get("_nome") or "", "cpf": row_b.get("_cpf") or "",
                                "matricula": row_b.get("_matricula") or "", "nascimento": str(row_b.get("_nascimento") or "")},
            })
        pares_possiveis.sort(key=lambda p: p["similaridade"], reverse=True)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500

    return jsonify({
        "job_id": job_id,
        "registros_encontrados": resultado.records_found,
        "duplicidades_confirmadas": resultado.confirmed_duplicates_pairs,
        "possiveis_duplicidades": resultado.possible_duplicates_pairs,
        "pares_possiveis": pares_possiveis,
    })


@app.route("/api/finalizar", methods=["POST"])
def finalizar():
    payload = request.get_json(silent=True) or {}
    job_id = payload.get("job_id", "")
    decisoes = payload.get("decisoes", {})

    job = _jobs.get(job_id)
    if not job or "process_result" not in job:
        return jsonify({"erro": "Sessão expirada — envie os arquivos novamente."}), 404

    # TUDO daqui pra baixo agora está protegido — antes, um erro em
    # qualquer etapa ANTES da escrita do Excel (aplicar as decisões de
    # duplicidade, montar os registros) não caía em nenhum try/except,
    # e o Flask devolvia uma página de erro em HTML em vez de JSON. O
    # JavaScript tentava interpretar aquilo como JSON e falhava
    # silenciosamente — por isso "não acontecia nada" na tela, sem
    # nenhuma mensagem de erro visível.
    try:
        resultado = job["process_result"]
        df_sem_confirmadas = pipeline.resolve_confirmed_duplicates(resultado)
        df_final = pipeline.apply_user_decisions(df_sem_confirmadas, decisoes) if decisoes else df_sem_confirmadas

        registros = pipeline.build_output_records(df_final)

        output_path = job["job_dir"] / "Base de Vidas Tratada.xlsx"
        excel_writer.write_output(MODELO_PADRAO, output_path, registros)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()  # aparece no terminal onde o 'py app.py' está rodando
        return jsonify({"erro": f"Erro ao gerar o arquivo final: {e}"}), 500

    job["output_path"] = output_path

    return jsonify({
        "download_url": f"/api/download/{job_id}",
        "vidas_finais": len(registros),
    })


@app.route("/api/download/<job_id>")
def download(job_id: str):
    job = _jobs.get(job_id)
    output_path = job.get("output_path") if job else None
    if not output_path or not output_path.exists():
        abort(404)
    return send_file(output_path, as_attachment=True, download_name="Base de Vidas Tratada.xlsx")


if __name__ == "__main__":
    import os
    porta = int(os.environ.get("PORT", 5002))
    print(f"Abrindo em http://localhost:{porta}")
    app.run(host="0.0.0.0", port=porta, debug=False)
