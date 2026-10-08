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
                        title: t('Chats und Jobs', 'Chats and jobs'),
                        body: t('Chats bleiben in der Seitenleiste gespeichert. Alle Chats löschen verlangt eine Bestätigung und kann nicht rückgängig gemacht werden. Files & Jobs zeigt Dateioperationen und Ergebnisse; die Job Queue zeigt Medien-Aufträge und bietet Abbrechen für unterstützte aktive Jobs. Je klarer Ziel, Format und Stil sind, desto gezielter kann nobby arbeiten.', 'Chats are saved in the sidebar. Delete all chats requires confirmation and cannot be undone. Files & Jobs shows file operations and results; the job queue shows media jobs and offers cancellation for supported active jobs. Clear goals, output format, and style help nobby work precisely.')
                    }
                ],
                examples: [
                    t('Fasse dieses Dokument in fünf Punkten zusammen und nenne offene Fragen.', 'Summarize this document in five bullets and list open questions.')
                ]
            },
            {
                id: 'finance',
                icon: '📈',
                title: t('Finanzanalyse', 'Finance Intelligence'),
                summary: t('Aktienkurse, Analysen, Vergleiche, Portfolio und frühere Empfehlungen.', 'Stock quotes, analysis, comparisons, portfolios and previous recommendations.'),
                sections: [
                    {
                        title: t('Kurse und Analysen', 'Quotes and analysis'),
                        body: t('Frage nach einem Aktienkurs, einer vollständigen fundamentalen und technischen Analyse oder einem Vergleich (z. B. „Wo steht Microsoft gerade?“). Bekannte Firmennamen wie Western Digital werden auf den verifizierten Börsenticker aufgelöst; ein neu ausdrücklich genanntes Unternehmen überschreibt immer den vorherigen Aktienkontext. Ergebnisse erscheinen als kompakte Finance-Karten mit Kurs, Performance und Bewertung; Rohdaten und Quellen liegen einklappbar darunter. Allgemeine Finanzbegriffe bleiben normale Wissensfragen; Unternehmensnews verwenden Websuche für Kontext. Kursdaten stammen aus dem Marktdatenprovider Yahoo Finance, niemals aus Web-News oder geschätzten Modellwerten.', 'Ask for a stock quote (e.g. “Where is Microsoft trading now?”), complete fundamental and technical analysis, or comparison. Known company names such as Western Digital resolve to the verified exchange ticker; a newly named company always replaces previous stock context. Results use compact Finance cards for price, performance and assessment, with raw details and sources collapsed below. General finance concepts remain knowledge questions; company news uses web search for context. Quotes come from the Yahoo Finance market data provider, never from web news or estimated model values.')
                    },
                    {
                        title: t('Börsenplatz, Währung und Datenalter', 'Exchange, currency and freshness'),
                        body: t('Jeder Kurs zeigt Ticker, Börsenplatz/Handelsplatz, Originalwährung, Session (Regular, Pre-Market oder After-Hours), Zeitstempel und Datenalter. Für die Anzeige werden Geldbeträge standardmäßig zuerst ungefähr in EUR dargestellt; bei USD-Notierungen steht der unveränderte Dollarwert in Klammern. Die Umrechnung nutzt den täglichen Referenzkurs der Europäischen Zentralbank und ist kein Handels- oder Abrechnungskurs. AMD bedeutet weiterhin seine US-Notierung NASDAQ/USD; eine EUR-Anzeige ändert weder Börsenplatz noch Originalkurs, und Stuttgart/Xetra/EUR wird nicht mit NASDAQ/USD vermischt. Über 15 Minuten alte Kurse sind stale/veraltet, auch nach Börsenschluss. Die Verzögerung des kostenlosen Providers kann unbekannt sein; Echtzeit ist nicht garantiert. Fehlende und widersprüchliche Daten werden angezeigt.', 'Every quote shows ticker, exchange/trading venue, original currency, session (Regular, Pre-Market or After-Hours), timestamp and data age. Monetary values are shown approximately in EUR first; for USD listings the unchanged dollar amount remains in parentheses. Conversion uses the daily European Central Bank reference rate and is not a tradable or settlement FX rate. AMD still means its US listing NASDAQ/USD; EUR presentation never changes the exchange or original quote, and Stuttgart/Xetra/EUR is never mixed with NASDAQ/USD. Quotes older than 15 minutes are stale, including after the market closes. The free provider delay may be unknown; live data is not guaranteed. Missing and conflicting data is shown explicitly.')
                    },
                    {
                        title: t('Interaktiver Kursverlauf', 'Interactive price history'),
                        body: t('Kurskarten laden zusätzlich abgeschlossene Tageskurse und zeigen einen interaktiven Verlauf für 1 Monat, 3 Monate, 6 Monate, 1 Jahr, 2 Jahre und 5 Jahre. Mit Maus oder Touch kannst du über den Chart fahren und Datum sowie Kurswert ablesen; per Tastatur funktionieren Pfeiltasten, Home und End. Der Chart verwendet historische Schlusskurse in der Originalwährung. Die zusätzlich angezeigte EUR-Zahl ist nur eine ungefähre Umrechnung mit dem aktuellen täglichen EZB-Referenzkurs und kein historischer FX-Kurs.', 'Quote cards additionally load completed daily closes and show an interactive range for 1 month, 3 months, 6 months, 1 year, 2 years and 5 years. Hover or touch the chart to inspect date and price; keyboard users can use the arrow keys, Home and End. The chart uses historical closes in the original listing currency. The additional EUR figure is only an approximate conversion using the current daily ECB reference rate, not a historical FX rate.')
                    },
                    {
                        title: t('Score, Recommendation und Confidence', 'Score, recommendation and confidence'),
                        body: t('Ein deterministischer Score von 0–100 gewichtet Fundamental 20%, Growth 20%, Valuation 20%, Technical 15%, Momentum 10%, Sentiment 5% und Risk 10%. 85–100 Strong Buy, 70–84 Buy, 55–69 Hold, 40–54 Reduce, 0–39 Sell. Mindestens 70% Datenabdeckung einschließlich Fundamental, Growth und Valuation sowie frische, datierte Daten sind erforderlich. Sonst erscheint insufficient data statt einer erfundenen Empfehlung. Confidence beschreibt Datenvollständigkeit und Aktualität, nicht Gewinnwahrscheinlichkeit. Regeln sind heuristisch und nicht als profitable Strategie validiert. Fehlendes belastbares Sentiment bleibt leer.', 'A deterministic 0–100 score weights Fundamental 20%, Growth 20%, Valuation 20%, Technical 15%, Momentum 10%, Sentiment 5% and Risk 10%. 85–100 Strong Buy, 70–84 Buy, 55–69 Hold, 40–54 Reduce, 0–39 Sell. At least 70% coverage including Fundamental, Growth and Valuation, plus fresh dated data, is required. Otherwise insufficient data replaces a fabricated recommendation. Confidence describes completeness and freshness, not profit probability. Rules are heuristic and not validated as a profitable strategy. Missing reliable sentiment stays unavailable.')
                    },
                    {
                        title: t('Portfolio und Recommendation Tracking', 'Portfolio and recommendation tracking'),
                        body: t('Gib Positionen mit Stückzahlen an: Analysiere mein Portfolio: AMD: 10, NVDA: 5. Gewichtung, Konzentration, verfügbare Sektoren und tägliche Korrelationen werden lokal berechnet. Stückzahlen werden nicht extern gesendet. Originalwerte bleiben unverändert; soweit EZB-Referenzkurse verfügbar sind, zeigt das Portfolio zusätzlich ungefähre EUR-Werte und einen EUR-Gesamtwert. Analysen im gebundenen Chat werden lokal unveränderlich gespeichert; frage später, wie sich frühere Empfehlungen entwickelt haben. Die letzten 20 Analysen zeigen unbereinigte Kursänderungen ab dem gespeicherten Empfehlungskurs. Historische Tagesrendite, Benchmark-Alpha und Drawdown haben ein separates, datiertes Tageskursfenster. Dividenden und Splits fehlen in der Kursänderung. Treffer werden frühestens nach 90 Tagen und ohne erkannte Corporate Actions gewertet; Hold hat keine Trefferwertung. Tracking benötigt denselben Chat. Keine Orderausführung, keine Trading-Konten.', 'Provide positions and quantities: Analyze my portfolio: AMD: 10, NVDA: 5. Weights, concentration, available sectors and daily correlations are calculated locally. Quantities are never sent externally. Original values remain unchanged; when ECB reference rates are available, the portfolio additionally shows approximate EUR values and an EUR display total. Analyses in a bound chat are stored locally as immutable snapshots; later ask how previous recommendations performed. The latest 20 analyses show unadjusted price changes from the saved recommendation price. Historical daily returns, benchmark alpha and drawdown use a separate dated daily-close window. Price changes exclude dividends and splits. Hits require at least 90 days and no detected corporate actions; Hold has no hit classification. Tracking requires the same chat. No order execution or trading accounts.')
                    },
                    {
                        title: t('Quellen und Grenzen', 'Sources and limitations'),
                        body: t('Yahoo Finance ist ein kostenloser, nicht garantierter Marktdatenzugang ohne API-Key. Für reine Anzeigeumrechnungen nach EUR wird zusätzlich der tägliche Referenzkurs der Europäischen Zentralbank verwendet. Fundamentaldaten können gesperrt oder unvollständig sein. Jede verfügbare Datenart nennt Quelle und Abrufzeit; das Fundamental-Datum ist das letzte berichtete Quartalsende, falls geliefert. News müssen Tickerbezug, Datum und Quelle haben und höchstens 7 Tage alt sein. Makroeinflüsse, Katalysatoren und Sentiment werden ohne belastbare Quelle nicht angenommen. Technische Kennzahlen verwenden abgeschlossene Tageskurse. Providerfehler erzeugen keine erfundenen Werte. TradingAgents wird nicht benötigt. Details: docs/FINANCE.md.', 'Yahoo Finance is a free, non-guaranteed market data access without an API key. Presentation-only EUR conversions additionally use the daily European Central Bank reference rate. Fundamentals may be restricted or incomplete. Every available data type identifies its source and fetch time; the fundamentals date is the last reported quarter end when supplied. News must identify ticker relevance, date and source and be at most 7 days old. Macro influences, catalysts and sentiment are not assumed without reliable sources. Technical indicators use completed daily closes. Provider errors never create invented values. TradingAgents is not required. Details: docs/FINANCE.md.')
                    }
                ],
                examples: [
                    t('Wie steht AMD gerade?', 'How is AMD trading right now?'),
                    t('Analysiere AMD fundamental und technisch.', 'Analyze AMD fundamentally and technically.'),
                    t('Vergleiche AMD und NVIDIA.', 'Compare AMD and NVIDIA.'),
                    t('Welche Risiken siehst du bei AMD?', 'What risks do you see in AMD?'),
                    t('Analysiere mein Portfolio: AMD: 10, NVDA: 5.', 'Analyze my portfolio: AMD: 10, NVDA: 5.')
                ]
            },
            {
                id: 'images',
                icon: '🖼️',
                title: t('Bilder erstellen', 'Create images'),
                summary: t('1–6 Bilder, Gallery, Varianten, Referenzbilder und Bearbeitung.', '1–6 images, gallery, variants, reference images, and editing.'),
                sections: [
                    {
                        title: t('Guter Bild-Prompt', 'A good image prompt'),
                        body: t('Beschreibe Motiv, Stil, Licht, Perspektive, Stimmung und gewünschtes Format. Für realistische Bilder helfen konkrete Kamera- und Lichtsituationen.', 'Describe the subject, style, lighting, perspective, mood, and desired format. For realistic images, concrete camera and lighting details help.'),
                        steps: [
                            t('Motiv und Umgebung festlegen.', 'Define the subject and environment.'),
                            t('Stil, Licht und Perspektive ergänzen.', 'Add style, lighting, and perspective.'),
                            t('1–6 Bilder, Format, Qualität und optional einen Negative Prompt wählen.', 'Choose 1–6 images, format, quality, and optionally a negative prompt.')
                        ]
                    },
                    {
                        title: t('Bild bearbeiten', 'Edit an image'),
                        body: t('Hänge ein Bild an oder wähle ein aktives Bild und beschreibe die Änderung. Für ein neues Motiv mit derselben oder einer ähnlichen Person fordere ausdrücklich ein Referenzbild an. Beide Wege benötigen ein verfügbares lokales Edit-Modell; die Identität ist nicht garantiert.', 'Attach an image or select an active image and describe the change. For a new scene with the same or a similar person, explicitly request reference image generation. Both paths need an available local edit model; identity is not guaranteed.')
                    },
                    {
                        title: t('Gallery und Bildaktionen', 'Gallery and image actions'),
                        body: t('Wähle in der Gallery das Bild für weitere Schritte. Ein Klick auf das Bild öffnet die Vorschau; Download speichert es. Bild verbessern skaliert es hoch, Regenerate erzeugt ein neues Ergebnis, Varianten ändern den Seed bei gleichen wirksamen Einstellungen. Retry wiederholt fehlgeschlagene Slots; Abbrechen behält fertige Bilder. Qualität, Format, Negative Prompt und verfügbare Aktionen hängen vom Modell und Provider ab. Technische Details: docs/IMAGE_GALLERY_VARIANTS.md und docs/IMAGE_REFERENCE_GENERATION.md.', 'Select a gallery image for follow-up actions. Click the image to open its preview; Download saves it. Improve image upscales it, Regenerate creates a new result, and variants change the seed with the same effective settings. Retry repeats failed slots; cancelling keeps completed images. Quality, format, negative prompt, and available actions depend on the model and provider. Technical details: docs/IMAGE_GALLERY_VARIANTS.md and docs/IMAGE_REFERENCE_GENERATION.md.')
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
                summary: t('Im Chat planen, als Draft prüfen und ausdrücklich rendern.', 'Plan in chat, review a draft, and explicitly render it.'),
                sections: [
                    {
                        title: t('Vom Draft zum fertigen Short', 'From draft to finished Short'),
                        body: t('Planung und Produktion sind getrennt. Im Chat plant nobby den Short, speichert einen Draft und beendet den Turn. Dabei werden keine Bilder oder Videos produziert. Erst Render Short im Studio startet den Produktionsjob.', 'Planning and production are separate. In chat, nobby plans the Short, saves a draft, and ends the turn. No images or videos are produced at this stage. Only Render Short in Studio starts the production job.'),
                        steps: [
                            t('Thema, Länge, Stil und Zielplattform im Chat beschreiben.', 'Describe topic, duration, style, and target platform in chat.'),
                            t('Den gespeicherten Draft über die Chat-Nachricht im Shorts Studio öffnen.', 'Open the saved draft in Shorts Studio from the chat message.'),
                            t('Draft prüfen: Briefing, Szenen, Narration und sichtbare Captions bearbeiten und bei Bedarf neu planen.', 'Review the draft: edit briefing, scenes, narration, and visible captions; replan if needed.'),
                            t('Optional Expert Settings für Kamera, Kontinuität, Stimme, Musik, SFX und Übergänge öffnen.', 'Optionally open Expert Settings for camera, continuity, voice, music, SFX, and transitions.'),
                            t('Render Short wählen. Erst jetzt beginnt die Video-, Voiceover- und FFmpeg-Produktion gemäß deinen Einstellungen.', 'Select Render Short. Video, voiceover, and FFmpeg production now begins according to your settings.'),
                            t('Fortschritt in History verfolgen und das fertige Video öffnen oder downloaden.', 'Follow progress in History and open or download the finished video.')
                        ]
                    },
                    {
                        title: t('Drafts, History und Retry', 'Drafts, History, and retry'),
                        body: t('Änderungen werden automatisch gespeichert; bei einem Speicherfehler im Editor bleiben und erneut speichern. History bietet Retry für fehlgeschlagene oder abgebrochene Jobs, Duplicate für fertige Projekte und einen Cancel-Button für aktive Jobs. Cancel bricht den Job über den Agent ab und aktualisiert die History; Drafts und fertige Medien bleiben erhalten. Retry erstellt eine neue Revision und verwendet gültige fertige Medien erneut. Bei zu langem Voiceover Narration kürzen oder Sprechgeschwindigkeit anpassen. Verträge und Fehlerdetails: docs/SHORTS_STUDIO.md.', 'Changes autosave; if saving fails, stay in the editor and save again. History offers Retry for failed or cancelled jobs, Duplicate for completed projects, and a Cancel button for active jobs. Cancel stops the job through the Agent and refreshes History; drafts and completed media remain available. Retry creates a new revision and reuses valid completed media. If voiceover is too long, shorten narration or adjust voice speed. Contracts and error details: docs/SHORTS_STUDIO.md.')
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
                        title: t('Diktat und lokale Stimmen', 'Dictation and local voices'),
                        body: t('Starte Diktat über das Mikrofon, erlaube den Browserzugriff und stoppe die Aufnahme. Die lokale Transkription wird ins Eingabefeld übernommen; prüfe sie vor dem Absenden. Im Stimmenmanager kannst du lokale Stimmen testen und verwalten. Eine eingerichtete geklonte Stimme ist ebenfalls auswählbar.', 'Start dictation using the microphone, allow browser access, and stop recording. Local transcription fills the prompt box; review it before sending. Use the voice manager to test and manage local voices. A configured cloned voice can also be selected.')
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
                        body: t('Mit aktivem Coding-Workspace läuft jede Eingabe als workspacegebundene Agent-Aufgabe; ohne Workspace kehrst du zum normalen Chat zurück. Fragen und Reviews können rein lesend bleiben. Für Änderungen prüfst du Diff und Testergebnis vor der Freigabe zum Anwenden. Anhänge werden in diesem Workspace-Modus nicht unterstützt. Details: docs/AGENT_TASK_MODE.md.', 'With an active coding workspace, every prompt runs as a workspace-bound agent task; closing the workspace returns to normal chat. Questions and reviews can remain read-only. For changes, review the diff and test result before approving application. Attachments are not supported in this workspace mode. Details: docs/AGENT_TASK_MODE.md.')
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
                        body: t('Die Rollen sind chat, agent, coding, vision, vision_uncensored, image und embedding. Bildverständnis bevorzugt vision_uncensored, wenn verfügbar, sonst vision. Wähle Rollen passend zu den lokal verfügbaren Modellen; Video und Sprache haben eigene Dienste.', 'The roles are chat, agent, coding, vision, vision_uncensored, image, and embedding. Image understanding prefers vision_uncensored when available, otherwise vision. Assign roles to suitable locally available models; video and speech have their own services.')
                    },
                    {
                        title: t('Modellwahl', 'Choosing a model'),
                        body: t('Model Scout in der Modellansicht sucht auf Hugging Face und bewertet lokale Kompatibilität. Ein Discovery-Score ist kein Qualitätsbenchmark. Downloads und lokale A/B-Benchmarks startest du ausdrücklich; Benchmarks wechseln das geladene Modell vorübergehend.', 'Model Scout in the model view searches Hugging Face and checks local compatibility. A discovery score is not a quality benchmark. Downloads and local A/B benchmarks are explicit actions; benchmarks temporarily switch the loaded model.')
                    }
                ],
                examples: []
            },
            {
                id: 'memory',
                icon: '💭',
                title: t("Memory & Kontext", "Memory & context"),
                summary: t("Erinnerungen, Memory Manager und Context Inspector.", "Memories, Memory Manager, and Context Inspector."),
                sections: [
                    {
                        title: t("Erinnern und vergessen", "Remember and forget"),
                        body: t("Mit „Merk dir: …“ speicherst du dauerhafte Fakten oder Vorlieben. „Vergiss …“ entfernt passende Erinnerungen einschließlich verbundener historischer Varianten. Normale Fragen werden nicht automatisch gespeichert. Relevante Erinnerungen ergänzen lokale Chat-/Agent-Antworten; aktuelle Anweisungen haben Vorrang.", "Use “Remember that …” to store durable facts or preferences. “Forget …” removes matching memories including connected historical variants. Ordinary questions are not automatically stored. Relevant memories enrich local chat/agent responses; current instructions take precedence.")
                    },
                    {
                        title: t("Verwalten und prüfen", "Manage and inspect"),
                        body: t("Unter Einstellungen → Memory kannst du suchen, hinzufügen, bearbeiten, pinnen, deaktivieren und löschen. Bereinigen konsolidiert Duplikate; absorbierte Varianten bleiben deaktiviert prüfbar. Der Context Inspector zeigt für eine Testfrage den ausgewählten Kontext, ohne Nutzungszähler zu ändern. Details: docs/MEMORY.md, docs/MEMORY_MANAGER.md und docs/MEMORY_CONTEXT_INSPECTOR.md.", "Under Settings → Memory you can search, add, edit, pin, disable, and delete entries. Clean up consolidates duplicates; absorbed variants remain available for inspection while disabled. The Context Inspector shows selected context for a test query without changing usage counters. Details: docs/MEMORY.md, docs/MEMORY_MANAGER.md, and docs/MEMORY_CONTEXT_INSPECTOR.md.")
                    },
                ],
                examples: []
            },
            {
                id: 'automations',
                icon: '⏰',
                title: t("Automationen & Benachrichtigungen", "Automations & notifications"),
                summary: t("Lokale Zeitpläne, Ergebnisse und Benachrichtigungen.", "Local schedules, results, and notifications."),
                sections: [
                    {
                        title: t("Aufgaben planen", "Schedule tasks"),
                        body: t("Unter Einstellungen → Automationen erstellst du Agent-Aufgaben oder Model-Scout-Suchen. Wähle manuell, stündlich, täglich oder wöchentlich und prüfe Zeitzone und Workspace. Der native Agent muss laufen; Freigaberegeln gelten weiterhin. Eine wartende Freigabe erfordert deine Entscheidung.", "Under Settings → Automations create agent tasks or Model Scout searches. Choose manual, hourly, daily, or weekly execution and check timezone and workspace. The native agent must be running; approval rules still apply. A pending approval requires your decision.")
                    },
                    {
                        title: t("Ergebnisse prüfen", "Review results"),
                        body: t("Ausführungen und Benachrichtigungen bleiben lokal gespeichert. Im Benachrichtigungsbereich kannst du Ergebnisse öffnen und als gelesen markieren; macOS-Zustellung kann von lokalen Berechtigungen abhängen. Nach Agent-Neustart werden unterbrochene Ausführungen als fehlgeschlagen markiert, nicht automatisch fortgesetzt. Details: docs/AUTOMATIONS.md.", "Runs and notifications are stored locally. Open results and mark them read in the notification area; macOS delivery can depend on local permissions. After an agent restart, interrupted runs are marked failed rather than automatically resumed. Details: docs/AUTOMATIONS.md.")
                    },
                ],
                examples: []
            },
            {
                id: 'diagnostics',
                icon: '📊',
                title: t("System & Diagnose", "System & diagnostics"),
                summary: t("System Health, Self-Healing, Routing und Performance Observatory.", "System Health, self-healing, routing, and Performance Observatory."),
                sections: [
                    {
                        title: t("System Health", "System Health"),
                        body: t("Unter Einstellungen → System → Server findest du Dienstzustand, laufende Jobs und Diagnose. Kopiere die Diagnose für Fehlerberichte. Restart startet einen ausgewählten Dienst; Self-Healing kann ungesunde Dienste neu starten und festhängende Bild-/Videojobs erneut anfordern. Prüfe laufende Arbeit vor diesen Aktionen. Details: docs/SYSTEM_HEALTH.md.", "Under Settings → System → Server inspect service health, active jobs, and diagnosis. Copy diagnosis for bug reports. Restart restarts one selected service; self-healing can restart unhealthy services and retry stuck image/video jobs. Review active work before these actions. Details: docs/SYSTEM_HEALTH.md.")
                    },
                    {
                        title: t("Routing und Performance", "Routing and performance"),
                        body: t("Routing Observatory unter Einstellungen → Tools zeigt Route, Rolle, Guards und Fallbacks mit redigierten Prompts. Feedback ändert das Routing nicht automatisch. Performance Observatory in der Serveransicht zeigt lokale Wartezeiten und Modell-/Medienmetriken; unbekannte Werte sind keine Nullmessung. Diagnoseansichten aktualisieren automatisch nur sichtbar. Details: docs/ROUTING_OBSERVATORY.md und docs/PERFORMANCE_OBSERVATORY.md.", "Routing Observatory under Settings → Tools shows routes, roles, guards, and fallbacks with redacted prompts. Feedback does not automatically change routing. Performance Observatory in the Server view shows local waits and model/media metrics; unknown values are not measured zeros. Diagnostic views refresh automatically only while visible. Details: docs/ROUTING_OBSERVATORY.md and docs/PERFORMANCE_OBSERVATORY.md.")
                    },
                ],
                examples: []
            },
            {
                id: 'api-integrations',
                icon: '🔌',
                title: t("API & Integrationen", "API & integrations"),
                summary: t("OpenAI-kompatible lokale API, virtuelle Rollen und Cline.", "OpenAI-compatible local API, virtual roles, and Cline."),
                sections: [
                    {
                        title: t("Lokaler Endpunkt", "Local endpoint"),
                        body: t("Base URL: http://127.0.0.1:8090/v1. GET /v1/models listet verfügbare virtuelle Rollen: mlx-nobby/coding, mlx-nobby/chat und mlx-nobby/agent. POST /v1/chat/completions unterstützt Text, Streaming und native Tool Calls je nach Modell. /v1 bezeichnet die API-Version, nicht den Nobby-Release.", "Base URL: http://127.0.0.1:8090/v1. GET /v1/models lists available virtual roles: mlx-nobby/coding, mlx-nobby/chat, and mlx-nobby/agent. POST /v1/chat/completions supports text, streaming, and native tool calls depending on the model. /v1 is the API version, not the Nobby release."),
                        code: "http://127.0.0.1:8090/v1"
                    },
                    {
                        title: t("Cline und Sicherheit", "Cline and security"),
                        body: t("Wähle in Cline OpenAI Compatible, die Base URL und mlx-nobby/coding. Cline führt seine Tools selbst aus. Die API ist stateless: der Client sendet den Verlauf; es entstehen keine Nobby-Chat-Historie und kein Memory-/RAG-Kontext. Keine Authentifizierung, nur Loopback; niemals direkt im LAN/Internet freigeben. Ein API-Key-Platzhalter ist kein Schutz. Ausführliche Einrichtung: docs/OPENAI_COMPATIBLE_API.md.", "In Cline select OpenAI Compatible, the base URL, and mlx-nobby/coding. Cline executes its own tools. The API is stateless: the client sends history; requests create no Nobby chat history and receive no memory/RAG context. No authentication, loopback only; never expose it directly to a LAN or the internet. An API-key placeholder provides no protection. Full setup: docs/OPENAI_COMPATIBLE_API.md.")
                    },
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
                        body: t('mlx restart startet den LLM-Runtime-Prozess neu. mlx restart-all startet die nativen Dienste neu, lässt aber einen gesunden Agenten laufen und baut das Web-Frontend nicht neu. Nach einem Code-Update nutze im Repository ./scripts/restart-all.sh: es baut das Web-Frontend neu und lädt auch den Agent-Code. Danach mlx doctor prüfen.', 'mlx restart restarts the LLM runtime process. mlx restart-all restarts native services but retains a healthy agent and does not rebuild the web frontend. After a code update, run ./scripts/restart-all.sh from the repository: it rebuilds the web frontend and reloads agent code too. Then check mlx doctor.'),
                        code: 'mlx status\nmlx restart-all'
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
            const searchable = [topic.id, topic.title, topic.summary,
                ...topic.sections.flatMap(section => [section.title, section.body, ...(section.steps || []), section.code || '']),
                ...(topic.examples || [])].join(' ');
            return searchable.toLocaleLowerCase(language() === 'de' ? 'de-DE' : 'en-US').includes(normalized);
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
