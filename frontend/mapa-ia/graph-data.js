/* Dados do mapa do ecossistema de IA da SuperFrio.
 * Conteúdo derivado da apresentação GoLive "Como Publicar Aplicações
 * Construídas com IA" (v3). Cada nó tem posição curada no viewBox 1000x620.
 * Para reorganizar: edite x/y (ou arraste no próprio mapa e ajuste depois).
 *
 * Sem módulos ES nem globais implícitos: exposto em window.MAPA_IA_DATA para
 * carregar como <script src> comum (compatível com o CSP script-src 'self'). */
(function () {
  "use strict";

  window.MAPA_IA_DATA = {
    eyebrow: "Ecossistema de IA · SuperFrio",
    title: "Como funciona a IA na SuperFrio",
    intro:
      "Pessoas de negócio constroem com IA, a triagem classifica cada caso e a TI publica com governança. Passe o mouse ou toque em um nó para ver como tudo se conecta.",
    hint: "Dica: arraste os nós (com o mouse) para reorganizar o mapa.",
    defaultId: "ecossistema",

    // type: core | pessoa | motor | triagem | entrega | planejado
    nodes: [
      { id: "ecossistema", label: "Ecossistema de IA", detailTitle: "Ecossistema de IA — SuperFrio", type: "core", primary: true, x: 500, y: 300, description: "Como a SuperFrio utiliza IA com governança: pessoas de negócio constroem com IA, a triagem classifica cada caso e a TI publica com segurança e rastreabilidade." },

      { id: "fusionTeam", label: "Fusion Team", type: "pessoa", primary: true, x: 235, y: 250, description: "Núcleo responsável pela execução dos projetos de IA (modelo Gartner, adotado por 84% das empresas): quem constrói, quem assume a parte técnica e quem prioriza. Nem todos que utilizam IA integram o time — o Fusion Team é o responsável pela execução." },
      { id: "acelerador", label: "Acelerador", type: "pessoa", primary: false, x: 105, y: 165, description: "Citizen developer: profissional de negócio que conhece a operação e desenvolve a solução com o apoio da IA. Detém o contexto do problema, conduz o projeto e entrega o pacote (zip) à TI; não interage diretamente com o Git." },
      { id: "engSolucao", label: "Eng. de Solução", detailTitle: "Engenharia de Solução / TI", type: "pessoa", primary: false, x: 90, y: 285, description: "Especialista / TI (platform engineering): define o padrão técnico, revisa o código, assume as Aplicações (banco de dados / AD) e conduz versionamento, publicação e governança técnica." },
      { id: "comite", label: "Comitê", detailTitle: "Comitê (Steering Committee)", type: "pessoa", primary: false, x: 120, y: 405, description: "Governança: prioriza a fila de demandas, aprova o que entra em produção e dá visibilidade ao negócio. Demandas recorrentes são consolidadas em uma solução única para toda a empresa." },
      { id: "diretoriaUsuarios", label: "Diretoria & Usuários", type: "pessoa", primary: false, x: 230, y: 510, description: "Fora do Fusion Team: utilizam IA para a própria produtividade (análises, decisões, tarefas do dia a dia), mas não executam projetos. São beneficiários, não executores." },

      { id: "motorIa", label: "Motor IA", detailTitle: "Motor de IA", type: "motor", primary: true, x: 390, y: 165, description: "A IA que potencializa os três papéis, da construção à revisão. Não é um integrante do time; é o motor utilizado por todos. Atualmente, na construção das aplicações, o motor é o Claude; o assistente interno (planejado) não necessariamente utilizará o mesmo motor." },

      { id: "triagem", label: "Triagem", detailTitle: "Triagem inteligente", type: "triagem", primary: true, x: 415, y: 455, description: "A IA classifica antes de construir. Em um projeto assistido por IA, o negócio é compreendido pelo uso concreto (sem jargão técnico), a complexidade real é identificada cedo e o caso é roteado em uma de três rotas." },
      { id: "eixoDado", label: "Guarda dado?", type: "triagem", primary: false, x: 300, y: 545, description: "1º eixo da triagem: a solução precisa armazenar dados — consultá-los depois, manter histórico? Em caso afirmativo, tende a ser uma Aplicação. A avaliação é feita pelo uso, por exemplo: será necessário consultar posteriormente o que foi preenchido antes?" },
      { id: "eixoSensivel", label: "Dado sensível?", type: "triagem", primary: false, x: 445, y: 560, description: "2º eixo da triagem: a solução envolve dado sensível ou de identidade (CPF, remuneração, dados de cliente)? Ainda que não haja banco de dados, isso altera a rota." },
      { id: "rotaArtefato", label: "Constrói e zipa", detailTitle: "Rota 1 · Constrói e entrega", type: "triagem", primary: false, x: 560, y: 435, description: "Artefato simples, sem dado sensível. O Acelerador desenvolve a solução com a IA, exporta o pacote (zip) e entrega à TI — sem uso de Git." },
      { id: "rotaSimplificar", label: "Simplificar", detailTitle: "Rota 2 · Simplificar", type: "triagem", primary: false, x: 545, y: 515, description: "A solução aparenta necessitar de banco de dados, mas talvez não. Antes de se tornar uma Aplicação, avalia-se aproveitar uma planilha ou SharePoint já existente — simplificar primeiro." },
      { id: "rotaEncaminhar", label: "Encaminha à TI", detailTitle: "Rota 3 · Encaminha à TI", type: "triagem", primary: false, x: 645, y: 500, description: "Há necessidade real de banco de dados ou AD. A conversa se converte em um levantamento de requisitos, pronto para a TI assumir a parte técnica." },

      { id: "artefato", label: "Artefato", type: "entrega", primary: false, x: 690, y: 555, description: "Ferramenta de tela, sem dado persistido e sem login — executa e entrega o resultado imediatamente (calculadora, simulador, formulário que gera PDF). Stateless, executada no navegador. O Acelerador conduz do início ao fim." },
      { id: "aplicacao", label: "Aplicação", type: "entrega", primary: false, x: 765, y: 480, description: "Sistema com dados persistidos, controle de usuário e/ou dado sensível — precisa ser mantido ao longo do tempo (registro de chamados, aprovações, cadastro consultável). Stateful, full-stack. A TI assume a parte técnica." },
      { id: "gitPR", label: "Git + PR", detailTitle: "Git + Pull Request", type: "entrega", primary: false, x: 800, y: 400, description: "Início do versionamento: a TI versiona o entregável, realiza o primeiro commit e revisa o código (padrão, segurança, dado sensível) em Pull Request, em janela semanal." },
      { id: "docker", label: "Docker", type: "entrega", primary: false, x: 875, y: 335, description: "A TI empacota a aplicação em uma imagem Docker (aplicação + runtime + bibliotecas, via Dockerfile). A mesma imagem executa de forma idêntica em desenvolvimento, homologação e produção." },
      { id: "deploy", label: "Deploy VM/AWS", detailTitle: "Deploy · VM / AWS", type: "entrega", primary: false, x: 930, y: 255, description: "Publicação do contêiner na VM / AWS EC2. Os usuários acessam pelo navegador na rede interna. Git (histórico de código) e tags Docker (histórico de releases) garantem rastreabilidade total." },
      { id: "hubPortal", label: "Hub / Portal", type: "entrega", primary: true, x: 820, y: 180, description: "O Hub/Portal disciplina o uso: catálogo de aplicações com controle de acesso por perfil (RBAC), registro do que está publicado e histórico de atualização. É onde as aplicações ficam disponíveis para os usuários." },

      { id: "assistenteIA", label: "Assistente IA interno", detailTitle: "Assistente IA interno (planejado)", type: "planejado", primary: true, x: 615, y: 150, description: "Assistente de IA interno para os colaboradores consultarem como a estrutura de IA da empresa funciona, a partir da documentação interna e sem que os dados saiam da empresa. Roadmap, ainda não implementado." },
      { id: "perguntasRespostas", label: "Perguntas & respostas", type: "planejado", primary: false, x: 500, y: 100, description: "Interface em que os colaboradores fazem perguntas em linguagem natural e recebem respostas com base no conhecimento interno." },
      { id: "baseConhecimento", label: "Base de conhecimento", type: "planejado", primary: false, x: 690, y: 92, description: "Base que alimenta as respostas: documentos, apresentações e guias sobre o funcionamento da estrutura de IA da SuperFrio (incluindo este mapa)." },
      { id: "dadosNaoSaem", label: "Dados não saem", detailTitle: "Dados não saem da empresa", type: "planejado", primary: false, x: 730, y: 235, description: "Requisito central: os dados internos não saem da empresa. A forma de garantir isso (modelo local, retenção zero de dados ou solução intermediária) é uma decisão de arquitetura ainda a definir." },
      { id: "govPermissoes", label: "Permissões", detailTitle: "Governança & permissões", type: "planejado", primary: false, x: 745, y: 315, description: "Define quem pode consultar quais informações. Reaproveita o controle de acesso por perfil (RBAC) do próprio Hub/Portal." }
    ],

    edges: [
      ["ecossistema", "fusionTeam"], ["ecossistema", "triagem"], ["ecossistema", "motorIa"],
      ["ecossistema", "hubPortal"], ["ecossistema", "assistenteIA"], ["ecossistema", "diretoriaUsuarios"],

      ["fusionTeam", "acelerador"], ["fusionTeam", "engSolucao"], ["fusionTeam", "comite"], ["fusionTeam", "motorIa"],

      ["motorIa", "triagem"], ["motorIa", "assistenteIA"],

      ["acelerador", "triagem"], ["acelerador", "artefato"],
      ["engSolucao", "aplicacao"], ["engSolucao", "gitPR"],
      ["comite", "gitPR"],

      ["triagem", "eixoDado"], ["triagem", "eixoSensivel"],
      ["triagem", "rotaArtefato"], ["triagem", "rotaSimplificar"], ["triagem", "rotaEncaminhar"],

      ["rotaArtefato", "artefato"], ["rotaSimplificar", "artefato"], ["rotaEncaminhar", "aplicacao"],

      ["artefato", "gitPR"], ["aplicacao", "gitPR"],
      ["gitPR", "docker"], ["docker", "deploy"], ["deploy", "hubPortal"],

      ["assistenteIA", "perguntasRespostas"], ["assistenteIA", "baseConhecimento"],
      ["assistenteIA", "dadosNaoSaem"], ["assistenteIA", "govPermissoes"],
      ["baseConhecimento", "ecossistema"], ["govPermissoes", "hubPortal"]
    ],

    typeLabels: {
      core: "Núcleo",
      pessoa: "Pessoas",
      motor: "Motor (IA)",
      triagem: "Triagem",
      entrega: "Entrega & Publicação",
      planejado: "Planejado"
    }
  };
})();
