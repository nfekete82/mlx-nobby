(function () {
    'use strict';

    if (window.__mlxHelpCenterLoaded) return;
    window.__mlxHelpCenterLoaded = true;

    function language() {
        return window.MLXI18n?.getLanguage?.() === 'de' ? 'de' : 'en';
    }

    function t(german, english) {
        return language() === 'de' ? german : english;
    }

    function topicData() {
        return [
            {
                id: 'getting-started',
                icon: '✨',
                title: t('Erste Schritte', 'Getting started'),
                summary: t('Chat, Modelle, Dateien und Workspaces verstehen.', 'Understand chat, models, files, and workspaces.'),
                sections: [
                    {
                        title: t('Schnellstart', 'Quick start'),
                        body: t('Schreibe deine Aufgabe einfach in das Eingabefeld. Du kannst zusätzlich Dateien anhängen, einen Workspace öffnen oder ein anderes Modell auswählen.', 'Describe your task in the prompt box. You can also attach files, open a workspace, or choose another model.'),
                        steps: [
                            t('Aufgabe oder Frage eingeben.', 'Enter a task or question.'),
                            t('Optional Dateien oder einen Workspace hinzufügen.', 'Optionally add files or a workspace.'),
                            t('Absenden und das Ergebnis direkt im Chat weiterbearbeiten.', 'Send it and continue refining the result in chat.')
                        ]
                    },
                    {
                        title: t('Tipp', 'Tip'),
                        body: t('Je klarer Ziel, Format und gewünschter Stil beschrieben sind, desto gezielter kann nobby arbeiten.', 'The clearer you describe the goal, output format, and desired style, the more precisely nobby can work.')
                    }
                ],
                examples: [
                    t('Fasse dieses Dokument in fünf Punkten zusammen und nenne offene Fragen.', 'Summarize this document in five bullets and list open questions.')
                ]
            },
            {
                id: 'images',
                icon: '🖼️',
                title: t('Bilder erstellen', 'Create images'),
                summary: t('Prompts, Qualität, Formate und Bildbearbeitung.', 'Prompts, quality, formats, and image editing.'),
                sections: [
                    {
                        title: t('Guter Bild-Prompt', 'A good image prompt'),
                        body: t('Beschreibe Motiv, Stil, Licht, Perspektive, Stimmung und gewünschtes Format. Für realistische Bilder helfen konkrete Kamera- und Lichtsituationen.', 'Describe the subject, style, lighting, perspective, mood, and desired format. For realistic images, concrete camera and lighting details help.'),
                        steps: [
                            t('Motiv und Umgebung festlegen.', 'Define the subject and environment.'),
                            t('Stil, Licht und Perspektive ergänzen.', 'Add style, lighting, and perspective.'),
                            t('Format und Qualitätsstufe auswählen.', 'Choose format and quality level.')
                        ]
                    },
                    {
                        title: t('Bild bearbeiten', 'Edit an image'),
                        body: t('Hänge ein vorhandenes Bild an und beschreibe nur die gewünschte Änderung. nobby routet die Anfrage an ein passendes Bildbearbeitungsmodell.', 'Attach an existing image and describe only the change you want. nobby routes the request to an appropriate image-editing model.')
                    }
                ],
                examples: [
                    t('Erstelle ein fotorealistisches Bild von Berlin bei Nacht, nasse Straßen, warme Neonlichter, cineastisch, 16:9.', 'Create a photorealistic image of Berlin at night, wet streets, warm neon lights, cinematic, 16:9.'),
                    t('Bearbeite dieses Bild: entferne den Hintergrund und mache das Licht wärmer.', 'Edit this image: remove the background and make the lighting warmer.')
                ]
            },
            {
                id: 'video',
                icon: '🎬',
                title: t('Videos erstellen', 'Create videos'),
                summary: t('Text-zu-Video und Bild-zu-Video mit LTX.', 'Text-to-video and image-to-video with LTX.'),
                sections: [
                    {
                        title: t('Text zu Video', 'Text to video'),
                        body: t('Beschreibe eine kurze, klar definierte Szene mit Handlung, Kamera, Licht und Stimmung. Kurze Szenen funktionieren meist besser als mehrere Ereignisse gleichzeitig.', 'Describe one short, clearly defined scene with action, camera, lighting, and mood. Short scenes usually work better than many events at once.')
                    },
                    {
                        title: t('Bild animieren', 'Animate an image'),
                        body: t('Hänge ein Bild an und beschreibe die gewünschte Bewegung. Nenne möglichst Kamerabewegung und Bewegung des Motivs getrennt.', 'Attach an image and describe the desired motion. It helps to describe camera movement and subject movement separately.')
                    }
                ],
                examples: [
                    t('Erstelle ein 5-sekündiges Video einer futuristischen Berliner Straße bei Regen, langsame Kamerafahrt nach vorne, cineastisch.', 'Create a 5-second video of a futuristic Berlin street in the rain, slow forward camera movement, cinematic.'),
                    t('Animiere dieses Bild: leichte Kamerafahrt nach rechts, Haare bewegen sich im Wind, natürliche Bewegung.', 'Animate this image: slight camera move to the right, hair moving in the wind, natural motion.')
                ]
            },
            {
                id: 'shorts',
                icon: '📱',
                title: t('Shorts erstellen', 'Create Shorts'),
                summary: t('Kompletter Media Composer aus einem einzigen Prompt.', 'Complete Media Composer from a single prompt.'),
                sections: [
                    {
                        title: t('Was automatisch passiert', 'What happens automatically'),
                        body: t('Der Shorts Composer plant die Szenen, erzeugt die Videoclips, erstellt das Voiceover, fügt Hintergrundmusik und Untertitel hinzu und setzt alles mit FFmpeg zu einem fertigen MP4 zusammen.', 'The Shorts Composer plans scenes, generates video clips, creates the voiceover, adds background music and subtitles, and combines everything with FFmpeg into a final MP4.'),
                        steps: [
                            t('Thema und gewünschte Länge beschreiben.', 'Describe the topic and desired length.'),
                            t('Optional Stil, Stimmung und Zielplattform ergänzen.', 'Optionally add style, mood, and target platform.'),
                            t('nobby plant und produziert die Szenen automatisch.', 'nobby plans and produces the scenes automatically.'),
                            t('Fortschritt verfolgen und das fertige Video im Chat öffnen.', 'Follow progress and open the finished video in chat.')
                        ]
                    },
                    {
                        title: t('Für bessere Ergebnisse', 'For better results'),
                        body: t('Ein klares Thema plus Dauer und Stil reicht meistens aus. Du musst die einzelnen Szenen nicht selbst planen.', 'A clear topic plus duration and style is usually enough. You do not need to plan each scene yourself.')
                    }
                ],
                examples: [
                    t('Erstelle ein 25-sekündiges YouTube Short darüber, wie Berlin im Jahr 2040 aussehen könnte. Futuristisch, glaubwürdig und cineastisch.', 'Create a 25-second YouTube Short about what Berlin could look like in 2040. Futuristic, believable, and cinematic.'),
                    t('Erstelle ein 20-sekündiges Short über fünf überraschende Fakten zum Mars, dynamisch und leicht verständlich.', 'Create a 20-second Short about five surprising facts about Mars, dynamic and easy to understand.')
                ]
            },
            {
                id: 'voice',
                icon: '🔊',
                title: t('Sprache & Stimmen', 'Speech & voices'),
                summary: t('Vorlesen, Diktat und lokale Stimmen verwenden.', 'Use read-aloud, dictation, and local voices.'),
                sections: [
                    {
                        title: t('Antworten vorlesen', 'Read responses aloud'),
                        body: t('Nutze die Vorlesefunktion an einer Antwort oder aktiviere automatisches Vorlesen. Die gewählte Stimme und Geschwindigkeit gelten für die Sprachausgabe.', 'Use the read-aloud action on a response or enable automatic reading. The selected voice and speed apply to speech output.')
                    },
                    {
                        title: t('Eigene lokale Stimme', 'Your own local voice'),
                        body: t('Wenn eine geklonte Stimme eingerichtet ist, kannst du sie wie andere Stimmen auswählen. Sprachdateien bleiben lokal und gehören nicht ins öffentliche Repository.', 'If a cloned voice is configured, you can select it like any other voice. Voice files stay local and do not belong in the public repository.')
                    }
                ],
                examples: []
            },
            {
                id: 'agent',
                icon: '🛠️',
                title: t('Agent-Modus', 'Agent mode'),
                summary: t('Tools, Workspaces, Freigaben und längere Aufgaben.', 'Tools, workspaces, approvals, and longer tasks.'),
                sections: [
                    {
                        title: t('Wann Agent verwenden?', 'When should I use Agent?'),
                        body: t('Agent eignet sich für mehrstufige Aufgaben, bei denen nobby Dateien, Code, lokale Tools oder einen Workspace selbstständig verwenden soll.', 'Agent is useful for multi-step tasks where nobby should work with files, code, local tools, or a workspace on its own.')
                    },
                    {
                        title: t('Freigaben', 'Approvals'),
                        body: t('Schreibende oder potenziell folgenreiche Aktionen können eine Freigabe verlangen. Prüfe dabei Ziel, Datei oder Befehl, bevor du bestätigst.', 'Write operations or potentially consequential actions may require approval. Check the target, file, or command before confirming.')
                    }
                ],
                examples: [
                    t('Analysiere dieses Projekt, finde die Ursache des Fehlers, behebe sie und führe die passenden Tests aus.', 'Analyze this project, find the cause of the bug, fix it, and run the relevant tests.')
                ]
            },
            {
                id: 'knowledge',
                icon: '📚',
                title: t('Dokumente & Wissen', 'Documents & knowledge'),
                summary: t('Dateien durchsuchen und lokale Wissensquellen nutzen.', 'Search files and use local knowledge sources.'),
                sections: [
                    {
                        title: t('Dokumente verwenden', 'Use documents'),
                        body: t('Hänge Dokumente an oder verwende die Wissensbasis. Bei Fragen zu langen Dokumenten sucht nobby relevante Abschnitte und bindet sie in die Antwort ein.', 'Attach documents or use the knowledge base. For questions about long documents, nobby searches relevant sections and uses them in the answer.')
                    },
                    {
                        title: t('Workspace-Kontext', 'Workspace context'),
                        body: t('Ein geöffneter Workspace gibt Agent und Coding einen klaren Projektkontext, ohne dass du jede Datei einzeln anhängen musst.', 'An open workspace gives Agent and Coding a clear project context without attaching every file individually.')
                    }
                ],
                examples: [
                    t('Suche in meinen Dokumenten nach allen Stellen zum Thema Modell-Routing und fasse die aktuelle Architektur zusammen.', 'Search my documents for everything about model routing and summarize the current architecture.')
                ]
            },
            {
                id: 'models',
                icon: '🧠',
                title: t('Modelle & Rollen', 'Models & roles'),
                summary: t('Chat, Agent, Coding, Vision und Media-Rollen verstehen.', 'Understand Chat, Agent, Coding, Vision, and media roles.'),
                sections: [
                    {
                        title: t('Rollen', 'Roles'),
                        body: t('MLX nobby kann unterschiedliche Modelle für Chat, Agent, Coding, Vision, Bilder und Embeddings verwenden. Ein Modellwechsel sollte nur die dafür vorgesehenen Rollen verändern.', 'MLX nobby can use different models for Chat, Agent, Coding, Vision, images, and embeddings. A model switch should only change the intended roles.')
                    },
                    {
                        title: t('Modellwahl', 'Choosing a model'),
                        body: t('Nutze ein schnelles Modell für alltägliche Aufgaben und ein stärkeres Modell für komplexes Coding, lange Analysen oder anspruchsvolle Vision-Aufgaben.', 'Use a fast model for everyday work and a stronger model for complex coding, long analysis, or demanding vision tasks.')
                    }
                ],
                examples: []
            },
            {
                id: 'troubleshooting',
                icon: '🩺',
                title: t('Fehlerbehebung', 'Troubleshooting'),
                summary: t('Dienste prüfen, Neustarten und typische Probleme eingrenzen.', 'Check services, restart them, and narrow down common problems.'),
                sections: [
                    {
                        title: t('System prüfen', 'Check the system'),
                        body: t('Nutze zuerst mlx doctor. Die Diagnose prüft Abhängigkeiten, lokale Dienste, Ports und den Revision-Status der laufenden Prozesse.', 'Start with mlx doctor. The diagnostic checks dependencies, local services, ports, and revision status of running processes.'),
                        code: 'mlx doctor'
                    },
                    {
                        title: t('Dienste neu starten', 'Restart services'),
                        body: t('Wenn Quellcode aktualisiert wurde, aber ein alter Prozess noch läuft, starte die Dienste kontrolliert neu und prüfe danach erneut den Status.', 'If source code was updated but an old process is still running, restart the services cleanly and check status again.'),
                        code: './scripts/restart-all.sh'
                    },
                    {
                        title: t('Wichtig', 'Important'),
                        body: t('Bei Änderungen am Agent-Code reicht ein Neustart des Runtime-Prozesses allein nicht aus. Der Agent-Dienst muss ebenfalls den neuen Code laden.', 'When Agent code changes, restarting only the runtime process is not enough. The Agent service must also load the new code.')
                    }
                ],
                examples: []
            }
        ];
    }

    function injectStyles() {
        if (document.getElementById('mlxHelpStyles')) return;
        const style = document.createElement('style');
        style.id = 'mlxHelpStyles';
        style.textContent = `
            .mlx-help-backdrop{position:fixed;inset:0;background:rgba(8,12,18,.46);backdrop-filter:blur(3px);z-index:1198}
            .mlx-help-panel{position:fixed;top:18px;right:18px;bottom:18px;width:min(920px,calc(100vw - 36px));z-index:1199;display:grid;grid-template-columns:260px minmax(0,1fr);overflow:hidden;border:1px solid rgba(127,140,160,.22);border-radius:18px;background:var(--panel-bg,#111821);box-shadow:0 24px 70px rgba(0,0,0,.34);color:inherit}
            .mlx-help-sidebar{display:flex;min-width:0;flex-direction:column;gap:12px;padding:18px 12px;border-right:1px solid rgba(127,140,160,.18);background:rgba(127,140,160,.055)}
            .mlx-help-brand{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:0 6px}
            .mlx-help-brand strong{font-size:1rem}.mlx-help-brand span{display:block;margin-top:2px;font-size:.74rem;opacity:.58}
            .mlx-help-close{border:0;background:transparent;color:inherit;font-size:1.5rem;line-height:1;cursor:pointer;opacity:.72}.mlx-help-close:hover{opacity:1}
            .mlx-help-search{width:100%;box-sizing:border-box;border:1px solid rgba(127,140,160,.2);border-radius:10px;background:rgba(127,140,160,.08);color:inherit;padding:9px 10px;outline:none}
            .mlx-help-search:focus{border-color:rgba(127,140,160,.5)}
            .mlx-help-topics{display:flex;min-height:0;overflow:auto;flex-direction:column;gap:4px}
            .mlx-help-topic{display:grid;grid-template-columns:28px minmax(0,1fr);gap:8px;align-items:center;width:100%;border:0;border-radius:10px;padding:9px 10px;background:transparent;color:inherit;text-align:left;cursor:pointer}
            .mlx-help-topic:hover{background:rgba(127,140,160,.09)}.mlx-help-topic.active{background:rgba(127,140,160,.15)}
            .mlx-help-topic-icon{font-size:1rem;text-align:center}.mlx-help-topic-copy{min-width:0}.mlx-help-topic-title{display:block;font-weight:650;font-size:.88rem}.mlx-help-topic-summary{display:block;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.7rem;opacity:.56}
            .mlx-help-main{min-width:0;overflow:auto;padding:28px 30px 40px}.mlx-help-hero{max-width:720px;margin-bottom:24px}.mlx-help-hero-icon{font-size:1.9rem}.mlx-help-hero h2{margin:8px 0 6px;font-size:1.65rem}.mlx-help-hero p{margin:0;opacity:.67;line-height:1.5}
            .mlx-help-section{max-width:720px;margin:0 0 22px}.mlx-help-section h3{margin:0 0 7px;font-size:1rem}.mlx-help-section p{margin:0;line-height:1.62;opacity:.82}.mlx-help-steps{margin:10px 0 0;padding-left:20px}.mlx-help-steps li{margin:6px 0;line-height:1.45;opacity:.82}
            .mlx-help-code{margin-top:10px;padding:10px 12px;border-radius:10px;background:rgba(0,0,0,.2);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.82rem;overflow:auto}
            .mlx-help-examples{max-width:720px;margin-top:28px;padding-top:20px;border-top:1px solid rgba(127,140,160,.16)}.mlx-help-examples h3{margin:0 0 12px;font-size:1rem}.mlx-help-example{display:flex;align-items:flex-start;gap:10px;margin:8px 0;padding:12px;border:1px solid rgba(127,140,160,.16);border-radius:12px;background:rgba(127,140,160,.045)}.mlx-help-example code{flex:1;white-space:normal;line-height:1.45;font-family:inherit;font-size:.82rem}.mlx-help-use{flex:0 0 auto;border:1px solid rgba(127,140,160,.2);border-radius:9px;background:rgba(127,140,160,.1);color:inherit;padding:7px 9px;cursor:pointer;font-size:.74rem}.mlx-help-use:hover{background:rgba(127,140,160,.18)}
            .mlx-help-empty{padding:24px 8px;opacity:.6;font-size:.84rem}
            @media(max-width:720px){.mlx-help-panel{top:8px;right:8px;bottom:8px;width:calc(100vw - 16px);grid-template-columns:1fr}.mlx-help-sidebar{max-height:42vh;border-right:0;border-bottom:1px solid rgba(127,140,160,.18)}.mlx-help-main{padding:22px 18px 32px}.mlx-help-topic-summary{display:none}}
        `;
        document.head.appendChild(style);
    }

    function make(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = text;
        return element;
    }

    let activeTopicId = 'getting-started';
    let previousFocus = null;

    function insertPrompt(prompt) {
        const input = document.getElementById('input');
        if (!input) return;
        input.value = prompt;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
        input.setSelectionRange?.(input.value.length, input.value.length);
        closeHelp();
    }

    function renderTopic() {
        const content = document.getElementById('mlxHelpContent');
        if (!content) return;
        const topics = topicData();
        const topic = topics.find(item => item.id === activeTopicId) || topics[0];
        content.replaceChildren();

        const hero = make('div', 'mlx-help-hero');
        hero.appendChild(make('div', 'mlx-help-hero-icon', topic.icon));
        hero.appendChild(make('h2', '', topic.title));
        hero.appendChild(make('p', '', topic.summary));
        content.appendChild(hero);

        topic.sections.forEach(section => {
            const block = make('section', 'mlx-help-section');
            block.appendChild(make('h3', '', section.title));
            block.appendChild(make('p', '', section.body));
            if (section.steps?.length) {
                const list = make('ol', 'mlx-help-steps');
                section.steps.forEach(step => list.appendChild(make('li', '', step)));
                block.appendChild(list);
            }
            if (section.code) block.appendChild(make('div', 'mlx-help-code', section.code));
            content.appendChild(block);
        });

        if (topic.examples?.length) {
            const examples = make('section', 'mlx-help-examples');
            examples.appendChild(make('h3', '', t('Beispiel-Prompts', 'Example prompts')));
            topic.examples.forEach(prompt => {
                const row = make('div', 'mlx-help-example');
                row.appendChild(make('code', '', prompt));
                const button = make('button', 'mlx-help-use', t('In Prompt einsetzen', 'Use prompt'));
                button.type = 'button';
                button.addEventListener('click', () => insertPrompt(prompt));
                row.appendChild(button);
                examples.appendChild(row);
            });
            content.appendChild(examples);
        }
    }

    function renderTopics(query = '') {
        const list = document.getElementById('mlxHelpTopics');
        if (!list) return;
        const normalized = String(query || '').trim().toLocaleLowerCase(language() === 'de' ? 'de-DE' : 'en-US');
        const topics = topicData().filter(topic => {
            if (!normalized) return true;
            return `${topic.title} ${topic.summary}`.toLocaleLowerCase(language() === 'de' ? 'de-DE' : 'en-US').includes(normalized);
        });
        list.replaceChildren();

        if (!topics.length) {
            list.appendChild(make('div', 'mlx-help-empty', t('Keine passenden Hilfethemen gefunden.', 'No matching help topics found.')));
            return;
        }

        topics.forEach(topic => {
            const button = make('button', `mlx-help-topic${topic.id === activeTopicId ? ' active' : ''}`);
            button.type = 'button';
            button.dataset.helpTopic = topic.id;
            button.appendChild(make('span', 'mlx-help-topic-icon', topic.icon));
            const copy = make('span', 'mlx-help-topic-copy');
            copy.appendChild(make('span', 'mlx-help-topic-title', topic.title));
            copy.appendChild(make('span', 'mlx-help-topic-summary', topic.summary));
            button.appendChild(copy);
            button.addEventListener('click', () => {
                activeTopicId = topic.id;
                renderTopics(document.getElementById('mlxHelpSearch')?.value || '');
                renderTopic();
            });
            list.appendChild(button);
        });
    }

    function refreshCopy() {
        const title = document.getElementById('mlxHelpTitle');
        const subtitle = document.getElementById('mlxHelpSubtitle');
        const search = document.getElementById('mlxHelpSearch');
        const close = document.getElementById('mlxHelpClose');
        const topButton = document.getElementById('mlxHelpButton');
        const sideButton = document.getElementById('mlxSidebarHelpButton');
        if (title) title.textContent = t('Hilfe', 'Help');
        if (subtitle) subtitle.textContent = t('MLX nobby verwenden', 'Using MLX nobby');
        if (search) search.placeholder = t('Hilfe durchsuchen…', 'Search help…');
        if (search) search.setAttribute('aria-label', t('Hilfe durchsuchen', 'Search help'));
        if (close) close.setAttribute('aria-label', t('Hilfe schließen', 'Close help'));
        if (topButton) {
            topButton.setAttribute('aria-label', t('Hilfe öffnen', 'Open help'));
            topButton.title = t('Hilfe öffnen', 'Open help');
        }
        if (sideButton) sideButton.querySelector('.sidebar-action-label').textContent = t('Hilfe', 'Help');
        renderTopics(search?.value || '');
        renderTopic();
    }

    function buildPanel() {
        if (document.getElementById('mlxHelpPanel')) return;
        injectStyles();

        const backdrop = make('div', 'mlx-help-backdrop');
        backdrop.id = 'mlxHelpBackdrop';
        backdrop.hidden = true;
        backdrop.addEventListener('click', closeHelp);

        const panel = make('section', 'mlx-help-panel');
        panel.id = 'mlxHelpPanel';
        panel.hidden = true;
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-modal', 'true');
        panel.setAttribute('aria-labelledby', 'mlxHelpTitle');

        const sidebar = make('aside', 'mlx-help-sidebar');
        const brand = make('div', 'mlx-help-brand');
        const brandCopy = make('div', '');
        const title = make('strong', '', t('Hilfe', 'Help'));
        title.id = 'mlxHelpTitle';
        const subtitle = make('span', '', t('MLX nobby verwenden', 'Using MLX nobby'));
        subtitle.id = 'mlxHelpSubtitle';
        brandCopy.append(title, subtitle);
        const close = make('button', 'mlx-help-close', '×');
        close.id = 'mlxHelpClose';
        close.type = 'button';
        close.addEventListener('click', closeHelp);
        brand.append(brandCopy, close);
        sidebar.appendChild(brand);

        const search = make('input', 'mlx-help-search');
        search.id = 'mlxHelpSearch';
        search.type = 'search';
        search.autocomplete = 'off';
        search.addEventListener('input', () => renderTopics(search.value));
        sidebar.appendChild(search);

        const topics = make('div', 'mlx-help-topics');
        topics.id = 'mlxHelpTopics';
        sidebar.appendChild(topics);

        const content = make('main', 'mlx-help-main');
        content.id = 'mlxHelpContent';
        panel.append(sidebar, content);
        document.body.append(backdrop, panel);
        refreshCopy();
    }

    function openHelp(topicId) {
        buildPanel();
        const topics = topicData();
        if (topicId && topics.some(topic => topic.id === topicId)) activeTopicId = topicId;
        previousFocus = document.activeElement;
        const backdrop = document.getElementById('mlxHelpBackdrop');
        const panel = document.getElementById('mlxHelpPanel');
        if (backdrop) backdrop.hidden = false;
        if (panel) panel.hidden = false;
        document.body.classList.add('mlx-help-open');
        refreshCopy();
        requestAnimationFrame(() => document.getElementById('mlxHelpSearch')?.focus());
    }

    function closeHelp() {
        const backdrop = document.getElementById('mlxHelpBackdrop');
        const panel = document.getElementById('mlxHelpPanel');
        if (backdrop) backdrop.hidden = true;
        if (panel) panel.hidden = true;
        document.body.classList.remove('mlx-help-open');
        previousFocus?.focus?.();
        previousFocus = null;
    }

    function installButtons() {
        const topActions = document.querySelector('.top-actions');
        if (topActions && !document.getElementById('mlxHelpButton')) {
            const button = make('button', 'icon-btn', '?');
            button.id = 'mlxHelpButton';
            button.type = 'button';
            button.addEventListener('click', () => openHelp());
            const before = document.getElementById('clearButton') || document.getElementById('settingsButton');
            topActions.insertBefore(button, before || null);
        }

        const sidebarBottom = document.querySelector('.sidebar-bottom');
        if (sidebarBottom && !document.getElementById('mlxSidebarHelpButton')) {
            const button = make('button', 'sidebar-action');
            button.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2-3 4"></path><path d="M12 17h.01"></path></svg>';
            button.appendChild(make('span', 'sidebar-action-label', t('Hilfe', 'Help')));
            button.id = 'mlxSidebarHelpButton';
            button.type = 'button';
            button.addEventListener('click', () => openHelp());
            const before = document.getElementById('sidebarSettingsButton');
            sidebarBottom.insertBefore(button, before || null);
        }
        refreshCopy();
    }

    function handleKeydown(event) {
        if (event.key === 'Escape' && !document.getElementById('mlxHelpPanel')?.hidden) {
            event.preventDefault();
            closeHelp();
        }
        if (event.key === '?' && event.shiftKey && !event.metaKey && !event.ctrlKey && !event.altKey) {
            const target = event.target;
            const typing = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target?.isContentEditable;
            if (!typing) {
                event.preventDefault();
                openHelp();
            }
        }
    }

    function init() {
        buildPanel();
        installButtons();
        document.addEventListener('keydown', handleKeydown);
        document.addEventListener('mlx-language-changed', refreshCopy);
        document.addEventListener('mlx-i18n-ready', refreshCopy);
    }

    window.MLXHelp = {
        open: openHelp,
        close: closeHelp,
        topics: () => topicData().map(topic => topic.id)
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
