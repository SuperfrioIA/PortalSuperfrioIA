    function toggleSenha() {
      var inp = document.getElementById('inp-senha');
      var btn = document.getElementById('btn-olho');
      if (inp.type === 'password') { inp.type = 'text'; btn.innerHTML = '&#128584;'; }
      else { inp.type = 'password'; btn.innerHTML = '&#128065;'; }
    }

    function el(id) { return document.getElementById(id); }

    var dados      = null;   // { usuario, senha, doca, conteudo }
    var qrPrintSrc = '';     // PNG preto puro usado na etiqueta
    var qrMatriz   = null;   // matriz de modulos do QR (redesenha sem perder nitidez)
    var qrModulos  = 0;      // qtd de modulos (dimensiona a magnificacao do ZPL)

    /* ---------------------------------------------------------------
       GEOMETRIA DA ETIQUETA - tudo em milimetros, origem no canto
       superior esquerdo. Fonte unica de verdade: o preview da tela,
       a impressao pelo driver, o PNG e o ZPL usam estas coordenadas.
    ---------------------------------------------------------------- */
    var QZ = 4;                      // modulos de zona de silencio embutidos na imagem do QR

    var ET = (function () {
      var W = 100, H = 50;
      var margem  = 1.5;             // folga minima nas bordas da etiqueta
      var nomeY   = 1.5;             // topo da faixa do nome
      var nomeH   = 6;               // altura fixa reservada ao nome (nao muda o QR)
      var gap     = 1;               // respiro entre o nome e o QR
      var qrY     = nomeY + nomeH + gap;
      var qrSize  = H - qrY - margem;    // QR no maior tamanho que cabe na altura
      return {
        W: W, H: H, pad: margem,
        qrX: 3, qrY: qrY, qrSize: qrSize,  // QR encostado a esquerda
        nomeY: nomeY, nomeH: nomeH,        // nome centralizado sobre o QR (mesma coluna)
        fsMax: 6, fsMin: 2.2
      };
    })();

    /* Corpo do nome: o maior que cabe na largura do QR (o nome fica
       centralizado exatamente sobre ele). A largura e medida de verdade,
       nao estimada, para nome nenhum vazar da coluna do QR. */
    var _medidor = null;
    function larguraPorCorpo(texto) {         // mm de largura para cada 1 mm de corpo
      if (!_medidor) _medidor = document.createElement('canvas').getContext('2d');
      _medidor.font = '700 100px Arial, Helvetica, sans-serif';
      return _medidor.measureText(texto).width / 100;
    }
    function fsNome() {
      var t = (dados && dados.usuario) ? dados.usuario : '';
      var w = t ? larguraPorCorpo(t) : 0;
      var fs = w > 0 ? ET.qrSize / w : ET.fsMax;
      return Math.max(ET.fsMin, Math.min(ET.fsMax, fs));
    }

    /* ---------------------------------------------------------------
       Gera o QR em canvas proprio, 1 modulo = N pixels inteiros.
       Evita borda serrilhada e usa preto puro (termica nao faz cinza).
    ---------------------------------------------------------------- */
    function canvasQRNitido(qr, alvoPx) {
      if (!qr || typeof qr.getModuleCount !== 'function') return null;

      var n     = qr.getModuleCount();
      var quiet = QZ;                      // zona de silencio exigida pela norma ISO
      var total = n + quiet * 2;
      var s     = Math.max(2, Math.floor(alvoPx / total));

      var mat = [];
      for (var r = 0; r < n; r++) {
        mat[r] = [];
        for (var col = 0; col < n; col++) mat[r][col] = !!qr.isDark(r, col);
      }

      var c = document.createElement('canvas');
      c.width = c.height = total * s;
      var x = c.getContext('2d');
      x.fillStyle = '#FFFFFF'; x.fillRect(0, 0, c.width, c.height);
      x.fillStyle = '#000000';
      for (var r2 = 0; r2 < n; r2++) {
        for (var c2 = 0; c2 < n; c2++) {
          if (mat[r2][c2]) x.fillRect((c2 + quiet) * s, (r2 + quiet) * s, s, s);
        }
      }
      return { canvas: c, modulos: n, matriz: mat };
    }

    /* Redesenha o QR direto no canvas do PNG, com as bordas de cada
       modulo travadas em pixel inteiro (sem borrao no redimensionamento). */
    function desenharQR(ctx, x0, y0, tam) {
      if (!qrMatriz) return;
      var n = qrMatriz.length, quiet = QZ, total = n + quiet * 2;
      var s = tam / total;
      ctx.fillStyle = '#FFFFFF'; ctx.fillRect(x0, y0, tam, tam);
      ctx.fillStyle = '#000000';
      for (var r = 0; r < n; r++) {
        for (var c = 0; c < n; c++) {
          if (!qrMatriz[r][c]) continue;
          var xa = Math.round(x0 + (c + quiet) * s), xb = Math.round(x0 + (c + quiet + 1) * s);
          var ya = Math.round(y0 + (r + quiet) * s), yb = Math.round(y0 + (r + quiet + 1) * s);
          ctx.fillRect(xa, ya, xb - xa, yb - ya);
        }
      }
    }

    function gerarQR() {
      var usuario = el('inp-usuario').value.trim().toUpperCase();   // nome sempre em maiusculo
      var senha   = el('inp-senha').value;                    // senha NAO leva trim: espaco pode ser valido
      var doca    = el('inp-doca').value.trim().toUpperCase();

      if (!usuario || !senha || !doca) {
        alert('Por favor, preencha todos os campos.');
        return;
      }
      if (typeof qrcode === 'undefined') {
        alert('A biblioteca de QR Code nao foi carregada.\n\n' +
              'Ela fica embutida neste proprio arquivo HTML - se o arquivo foi\n' +
              'editado ou truncado, peca uma copia nova ao TI.');
        return;
      }

      var conteudo = usuario + '\n' + senha + '\n' + doca;
      dados = { usuario: usuario, senha: senha, doca: doca, conteudo: conteudo };

      // Versao 0 = automatica: a biblioteca escolhe pelo tamanho real em
      // bytes UTF-8, entao nome com acento (Joao/Joao) nao estoura mais.
      var qr;
      try {
        qr = qrcode(0, 'M');
        qr.addData(conteudo);            // modo Byte, UTF-8 sem BOM
        qr.make();
      } catch (e) {
        alert('Nao foi possivel gerar o QR Code: ' + e.message);
        return;
      }

      // --- imagem do QR para a etiqueta (preto puro, alta resolucao) ---
      var nitido = canvasQRNitido(qr, 900);
      if (!nitido) {
        alert('Nao foi possivel desenhar o QR Code nesta maquina.');
        return;
      }
      qrPrintSrc = nitido.canvas.toDataURL('image/png');
      qrModulos  = nitido.modulos;
      qrMatriz   = nitido.matriz;

      el('etiqueta-preview').innerHTML = montarEtiqueta();
      el('area-etiqueta').innerHTML    = '';
      status('info', '');
      el('form-area').style.display = 'none';    // some com o formulario
      el('resultado').style.display = 'block';
    }

    /* ================= ETIQUETA 100 x 50 mm =================
       So o nome e o QR. Senha e doca viajam dentro do QR, nunca
       impressas em texto.                                        */
    function montarEtiqueta() {
      var f = function (mm) { return mm + 'mm'; };
      return '' +
        '<div class="etiqueta">' +
          '<div class="et-nome" style="left:' + f(ET.qrX) + ';top:' + f(ET.nomeY) +
            ';width:' + f(ET.qrSize) + ';height:' + f(ET.nomeH) +
            ';line-height:' + f(ET.nomeH) + ';font-size:' + f(fsNome()) + '">' +
            esc(dados.usuario) + '</div>' +
          '<img class="et-qr" src="' + qrPrintSrc + '" alt="QR Code de bipagem"' +
            ' style="left:' + f(ET.qrX) + ';top:' + f(ET.qrY) +
            ';width:' + f(ET.qrSize) + ';height:' + f(ET.qrSize) + '" />' +
        '</div>';
    }

    /* Mesma etiqueta desenhada em canvas, para salvar como PNG (300 dpi) */
    function etiquetaCanvas(pxMm) {
      pxMm = pxMm || (300 / 25.4);
      var p = function (mm) { return mm * pxMm; };
      var c = document.createElement('canvas');
      c.width  = Math.round(p(ET.W));
      c.height = Math.round(p(ET.H));

      var x = c.getContext('2d');
      x.imageSmoothingEnabled = false;
      x.fillStyle = '#FFFFFF'; x.fillRect(0, 0, c.width, c.height);
      x.fillStyle = '#000000';
      x.textBaseline = 'top';

      var fonte = function (mm) { return '700 ' + p(mm) + 'px Arial, Helvetica, sans-serif'; };

      x.textAlign    = 'center';
      x.textBaseline = 'middle';
      x.font = fonte(fsNome());
      x.fillText(dados.usuario,
                 p(ET.qrX + ET.qrSize / 2), p(ET.nomeY + ET.nomeH / 2),
                 p(ET.qrSize));

      desenharQR(x, p(ET.qrX), p(ET.qrY), p(ET.qrSize));

      return c;
    }

    function nomeArquivo(ext) {
      return 'etiqueta_' + dados.usuario.replace(/[^A-Za-z0-9._-]/g, '_') + '.' + ext;
    }

    function baixar(blob, arquivo) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = arquivo;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 5000);
    }

    function salvarImagem() {
      if (!dados) return;
      etiquetaCanvas().toBlob(function (b) {
        baixar(b, nomeArquivo('png'));
        status('ok', 'Etiqueta salva: ' + nomeArquivo('png') + ' (10 x 5 cm, 300 dpi).');
      }, 'image/png');
    }

    /* Caminho 1: driver do Windows (ZDesigner) - imprime o layout acima */
    function imprimirEtiqueta() {
      if (!dados) return;
      el('area-etiqueta').innerHTML = montarEtiqueta();
      status('info', 'Na janela de impressao selecione a Zebra, papel 100 x 50 mm, margens "Nenhuma" e escala 100%.');

      var img = el('area-etiqueta').querySelector('img');
      var go  = function () { window.print(); };
      if (img && img.decode) { img.decode().then(go)['catch'](go); }
      else { setTimeout(go, 150); }
    }

    /* ================= CAMINHO 2: ZPL NATIVO ================= */
    /* Escapa a carga util para uso com ^FH_ (indicador hexadecimal) */
    function zplData(s) {
      var out = '';
      for (var i = 0; i < s.length; i++) {
        var ch = s.charAt(i), cod = s.charCodeAt(i);
        if      (ch === '_')  out += '_5F';
        else if (ch === '^')  out += '_5E';
        else if (ch === '~')  out += '_7E';
        else if (cod < 32)    out += '_' + ('0' + cod.toString(16).toUpperCase()).slice(-2);
        else                  out += ch;
      }
      return out;
    }

    function gerarZPL(dpmm) {
      var d = function (mm) { return Math.round(mm * dpmm); };

      var n = qrModulos || 29;                                  // modulos do QR
      // O ^BQ imprime so os modulos, sem zona de silencio; a imagem da tela
      // ja traz QZ modulos embutidos. Descontando, os dois ficam do mesmo tamanho.
      var util = ET.qrSize * n / (n + QZ * 2);
      var mag  = Math.max(1, Math.min(10, Math.floor(util * dpmm / n)));   // ^BQ vai ate 10
      var real = (n * mag) / dpmm;
      var off  = (ET.qrSize - real) / 2;
      var xQR  = ET.qrX + off;
      var yQR  = ET.qrY + off;

      var z = [];
      z.push('^XA');
      z.push('^CI28');                                            // UTF-8
      z.push('^PW' + d(ET.W));                                    // largura 100 mm
      z.push('^LL' + d(ET.H));                                    // altura  50 mm
      z.push('^LH0,0');
      z.push('^LT0');
      // nome do usuario no topo, centralizado na mesma coluna do QR
      var fsN  = fsNome();
      var yNom = ET.nomeY + (ET.nomeH - fsN) / 2;
      z.push('^FO' + d(ET.qrX) + ',' + d(yNom) + '^A0N,' + d(fsN) + ',' + d(fsN) +
             '^FB' + d(ET.qrSize) + ',1,0,C,0^FH_^FD' + zplData(dados.usuario) + '^FS');
      // QR nativo da impressora: ^BQ orientacao,modelo,magnificacao / ^FD<nivel><modo>,<dados>
      z.push('^FO' + d(xQR) + ',' + d(yQR) + '^BQN,2,' + mag +
             '^FH_^FDMA,' + zplData(dados.conteudo) + '^FS');
      z.push('^PQ1');
      z.push('^XZ');
      return z.join('\n');
    }

    /* Zebra Browser Print (agente local). Se nao existir, baixa o .zpl. */
    function escreverZebra(base, zpl) {
      var comTempo = function (p, ms) {
        return new Promise(function (ok, falha) {
          var t = setTimeout(function () { falha(new Error('tempo esgotado')); }, ms);
          p.then(function (v) { clearTimeout(t); ok(v); },
                 function (e) { clearTimeout(t); falha(e); });
        });
      };
      return comTempo(fetch(base + '/available'), 4000)
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (j) {
          var dev = (j && j.printer && j.printer[0]) || (j && j['default']) || null;
          if (!dev) throw new Error('nenhuma impressora disponivel no agente');
          return comTempo(fetch(base + '/write', {
            method: 'POST',
            headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
            body: JSON.stringify({ device: dev, data: zpl })
          }), 8000).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return dev.name || dev.uid || 'Zebra';
          });
        });
    }

    function enviarBrowserPrint(zpl) {
      var bases = ['http://localhost:9100', 'https://localhost:9101'];
      var tentar = function (i) {
        if (i >= bases.length) return Promise.reject(new Error('agente Browser Print nao respondeu'));
        return escreverZebra(bases[i], zpl)['catch'](function () { return tentar(i + 1); });
      };
      return tentar(0);
    }

    function imprimirZPL() {
      if (!dados) return;
      // O botao que chamava esta funcao foi retirado da tela a pedido da
      // operacao (nao usamos o envio ZPL direto para a Zebra). O codigo fica
      // aqui caso volte a ser necessario: basta recolocar o botao chamando
      // imprimirZPL() e, se quiser escolher o dpi, o seletor 'sel-dpi'.
      var sel  = el('sel-dpi');
      var dpmm = (sel && parseInt(sel.value, 10)) || 8;   // 203 dpi por padrao
      var zpl  = gerarZPL(dpmm);

      status('info', 'Procurando o agente Zebra Browser Print...');
      enviarBrowserPrint(zpl).then(function (nome) {
        status('ok', 'Etiqueta enviada para a impressora "' + nome + '".');
      })['catch'](function (e) {
        // Conteudo e ZPL puro (a linguagem da impressora), gravado com a
        // extensao .lbl a pedido da operacao. Atencao: o ZebraDesigner nao
        // abre ZPL - o arquivo serve para mandar direto para a impressora.
        // CRLF para o arquivo abrir certinho no Bloco de Notas do Windows.
        var arq = nomeArquivo('lbl');
        var txt = zpl.replace(/\r?\n/g, '\r\n');
        baixar(new Blob([txt], { type: 'text/plain;charset=utf-8' }), arq);
        status('err', 'Browser Print indisponivel (' + e.message + '). Baixei ' + arq +
                      ' na pasta Downloads: envie para a Zebra pelo Zebra Setup Utilities ' +
                      '(Open Communication With Printer > Send File) ou pelo Prompt de ' +
                      'Comando com copy /b "' + arq + '" \\\\servidor\\impressora.');
      });
    }

    function status(tipo, msg) {
      var s = el('status-print');
      if (!s) return;
      s.className = 'status ' + tipo;
      s.textContent = msg;
    }

    /* Deixa o campo em maiusculo enquanto o usuario digita, sem
       perder a posicao do cursor. */
    function maiusculo(campo) {
      var ini = campo.selectionStart, fim = campo.selectionEnd;
      campo.value = campo.value.toUpperCase();
      try { campo.setSelectionRange(ini, fim); } catch (e) {}
    }

    function esc(s) {
      return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    function limpar() {
      dados = null;
      qrPrintSrc = '';
      qrMatriz = null;
      qrModulos = 0;
      el('area-etiqueta').innerHTML    = '';
      el('etiqueta-preview').innerHTML = '';
      el('resultado').style.display = 'none';
      el('form-area').style.display = '';
      status('info', '');
    }

    function novoQR() {
      el('inp-usuario').value = '';
      el('inp-senha').value   = '';
      el('inp-doca').value    = 'DOCA01';
      el('inp-senha').type    = 'password';
      el('btn-olho').innerHTML = '&#128065;';
      limpar();
      el('inp-usuario').focus();
    }

    // Enter em qualquer campo gera o QR
    ['inp-usuario', 'inp-senha', 'inp-doca'].forEach(function (id) {
      el(id).addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); gerarQR(); }
      });
    });

    /* Listeners via addEventListener (nao onclick/oninput inline) - o CSP do
       portal (script-src 'self') bloqueia handler de evento inline tanto
       quanto <script> sem src. */
    el('inp-usuario').addEventListener('input', function () { maiusculo(this); limpar(); });
    el('inp-senha').addEventListener('input', limpar);
    el('inp-doca').addEventListener('input', limpar);
    el('btn-olho').addEventListener('click', toggleSenha);
    el('btn-gerar').addEventListener('click', gerarQR);
    el('btn-print').addEventListener('click', imprimirEtiqueta);
    el('btn-salvar').addEventListener('click', salvarImagem);
    el('btn-novo').addEventListener('click', novoQR);
