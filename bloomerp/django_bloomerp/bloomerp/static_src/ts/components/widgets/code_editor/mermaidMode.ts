import ace from 'ace-builds/src-noconflict/ace';
import type { Ace } from 'ace-builds';

const TextMode = ace.require('ace/mode/text').Mode;
const TextHighlightRules = ace.require('ace/mode/text_highlight_rules').TextHighlightRules;

/** Highlight Mermaid source without restricting the diagram types accepted by the renderer. */
class MermaidHighlightRules extends TextHighlightRules {
    /** Recognize diagram declarations, comments, strings, directions, and connections. */
    public constructor() {
        super();
        this.$rules = {
            start: [
                { token: 'comment', regex: '%%.*$' },
                { token: 'string', regex: '"(?:[^"\\\\]|\\\\.)*"' },
                { token: 'keyword.control', regex: '\\b(?:flowchart|graph|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|journey|gantt|pie|gitGraph|mindmap|timeline|quadrantChart|requirementDiagram|C4Context|C4Container|C4Component|C4Dynamic|C4Deployment|block-beta|architecture-beta|packet-beta|kanban|xychart-beta|sankey-beta)\\b' },
                { token: 'keyword', regex: '\\b(?:subgraph|end|participant|actor|activate|deactivate|autonumber|note|Note|over|as|loop|alt|else|opt|par|and|rect|break|critical|option|title|section|dateFormat|axisFormat|classDef|class|style|linkStyle|click|direction|accTitle|accDescr)\\b' },
                { token: 'constant.language', regex: '\\b(?:TB|TD|BT|LR|RL)\\b' },
                { token: 'keyword.operator', regex: '<[-.=]+>|[-.=]{2,}[>ox]?|->>|:::' },
                { token: 'constant.numeric', regex: '\\b\\d+(?:\\.\\d+)?\\b' },
                { token: 'paren.lparen', regex: '[\\[({]' },
                { token: 'paren.rparen', regex: '[\\])}]' },
            ],
        };
        this.normalizeRules();
    }
}

/** Create the syntax mode missing from Ace's bundled language catalog. */
export function createMermaidMode(): Ace.SyntaxMode {
    const mode = new TextMode();
    mode.$id = 'ace/mode/mermaid';
    mode.HighlightRules = MermaidHighlightRules;
    mode.lineCommentStart = '%%';
    return mode;
}
