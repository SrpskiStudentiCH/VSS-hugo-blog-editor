import React, { useEffect, useRef } from "react";
import SimpleMDE from "simplemde";
import DOMPurify from "dompurify";
import { marked } from "marked";
import "simplemde/dist/simplemde.min.css";

// SimpleMDE's default preview assigns marked() output to innerHTML. Content
// comes from the repository (untrusted), so sanitize it before it hits the DOM.
function renderPreview(text) {
    const html = marked.parse(text || "");
    return DOMPurify.sanitize(html, {
        FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select"],
        FORBID_ATTR: ["style"],
    });
}

export default function MarkdownEditor({ editorId = "simplemde-editor", content = "", setContent }) {

    // Stores the SimpleMDE editor instance
    const editorRef = useRef(null);

    useEffect(() => {
        // Initialize SimpleMDE editor
        editorRef.current = new SimpleMDE({
            element: document.getElementById(editorId), // textarea to convert into editor
            initialValue: content, // initial editor value
            spellChecker: false,   // disable spell checker
            previewRender: renderPreview, // sanitized HTML for preview panes
            toolbar: [             // toolbar buttons (same UX as the old editor)
                "bold", "italic", "heading", "quote", "code", "|",
                "unordered-list", "ordered-list", "|",
                "link", "image", "table", "|",
                "preview", "side-by-side", "fullscreen"
            ]
        });

        // Listen for content changes and update parent state
        editorRef.current.codemirror.on("change", () => {
            setContent(editorRef.current.value());
        });

        // Cleanup: destroy editor when component unmounts
        return () => {
            if (editorRef.current) {
                editorRef.current.toTextArea();
                editorRef.current = null;
            }
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [editorId]);

    useEffect(() => {
        // If external content changes, sync it with the editor
        if (editorRef.current && editorRef.current.value() !== content) {
            editorRef.current.value(content);
        }
    }, [content]);

    return (
        <div className="editor-panel">
            <h2>Sadržaj</h2>
            {/* The textarea SimpleMDE will attach to */}
            <textarea id={editorId}></textarea>
        </div>
    );
}
