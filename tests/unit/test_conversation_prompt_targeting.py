from types import SimpleNamespace

from experiments.gemini_conversation_20260730.run_experiment import prompt_elements


def test_chatgpt_prompt_targeting_excludes_occluded_file_inputs():
    prompt = {
        "element_id": "prompt",
        "dom_tag": "div",
        "semantic_role": "textbox",
        "accessible_name": "Chat with ChatGPT",
        "input_type": None,
        "visible": True,
        "editable": True,
        "occlusion_state": "not_occluded",
    }
    upload = {
        "element_id": "upload",
        "dom_tag": "input",
        "semantic_role": "textbox",
        "accessible_name": None,
        "input_type": "file",
        "visible": True,
        "editable": True,
        "occlusion_state": "occluded",
    }

    result = prompt_elements(SimpleNamespace(interactive_elements=[prompt, upload, upload]))

    assert result == [prompt]


def test_prompt_targeting_keeps_unoccluded_text_input():
    prompt = {
        "element_id": "prompt",
        "dom_tag": "textarea",
        "semantic_role": "textbox",
        "accessible_name": "Enter a prompt",
        "input_type": None,
        "visible": True,
        "editable": True,
        "occlusion_state": "not_occluded",
    }

    assert prompt_elements(SimpleNamespace(interactive_elements=[prompt])) == [prompt]
