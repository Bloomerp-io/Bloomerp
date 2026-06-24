import { EditorConfig, ElementNode, LexicalEditor } from "lexical";


export class GridNode extends ElementNode {
    __cols:number


    static getType(): string {
        return 'text-editor-grid'
    }

    createDOM(_config: EditorConfig, _editor: LexicalEditor): HTMLElement {
        const element = document.createElement('div')
        element.classList.add('grid')

        return element
    }

    


}