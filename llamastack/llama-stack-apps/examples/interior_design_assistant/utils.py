# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

import base64
import mimetypes

# TODO: This should move into a common util as will be needed by all apps
def data_url_from_image(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type is None:
        raise ValueError("Could not determine MIME type of the file")

    with open(file_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode("utf-8")

    data_url = f"data:{mime_type};base64,{encoded_string}"
    return data_url


def image_data_from_image(file_path):
    with open(file_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def create_single_turn(client, agent_kwargs, messages):
    """Create a single response and return output text."""
    response = client.responses.create(
        model=agent_kwargs.get("model"),
        instructions=agent_kwargs.get("instructions"),
        input=messages,
        stream=False,
    )
    return response.output_text
