# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

from typing import Any

from llama_stack_api import Api

from .config import WeatherToolRuntimeConfig


async def get_provider_impl(config: WeatherToolRuntimeConfig, deps: dict[Api, Any]):
    from .weather import WeatherToolRuntimeImpl

    impl = WeatherToolRuntimeImpl(config)
    await impl.initialize()
    return impl
