#!/usr/bin/env python3
"""
Unit tests for Math MCP Server
"""

import pytest
import asyncio
import json
from unittest.mock import Mock, patch, AsyncMock
from mcp.types import TextContent

# Import the handlers from math_mcp_server
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from math_mcp_server import (
    handle_calculate_expression,
    handle_solve_equation,
    handle_derivative,
    handle_integral,
    handle_matrix_operations,
    handle_statistics_calculator,
    list_tools,
    call_tool
)


class TestCalculateExpression:
    """Tests for calculate_expression tool"""
    
    @pytest.mark.asyncio
    async def test_simple_addition(self):
        result = await handle_calculate_expression({"expression": "2+2"})
        assert len(result) == 1
        assert "Result: 4" in result[0].text
    
    @pytest.mark.asyncio
    async def test_trigonometric_function(self):
        result = await handle_calculate_expression({"expression": "sin(pi/2)"})
        assert len(result) == 1
        assert "Result: 1" in result[0].text
    
    @pytest.mark.asyncio
    async def test_square_root(self):
        result = await handle_calculate_expression({"expression": "sqrt(16)"})
        assert len(result) == 1
        assert "Result: 4" in result[0].text
    
    @pytest.mark.asyncio
    async def test_symbolic_expression(self):
        result = await handle_calculate_expression({"expression": "x**2 + 2*x"})
        assert len(result) == 1
        assert "Result:" in result[0].text
        assert "x" in result[0].text
    
    @pytest.mark.asyncio
    async def test_empty_expression(self):
        result = await handle_calculate_expression({"expression": ""})
        assert len(result) == 1
        assert "Error: No expression provided" in result[0].text
    
    @pytest.mark.asyncio
    async def test_invalid_expression(self):
        # Test with malformed expression that SymPy cannot parse
        result = await handle_calculate_expression({"expression": "2 ++ ++ 3 @#$"})
        assert len(result) == 1
        assert "Error calculating expression" in result[0].text


class TestSolveEquation:
    """Tests for solve_equation tool"""
    
    @pytest.mark.asyncio
    async def test_linear_equation(self):
        result = await handle_solve_equation({"equation": "2*x + 5 = 11", "variable": "x"})
        assert len(result) == 1
        assert "Solutions for x: 3" in result[0].text
    
    @pytest.mark.asyncio
    async def test_quadratic_equation(self):
        result = await handle_solve_equation({"equation": "x**2 - 4 = 0", "variable": "x"})
        assert len(result) == 1
        assert "Solutions for x:" in result[0].text
        assert "-2" in result[0].text and "2" in result[0].text
    
    @pytest.mark.asyncio
    async def test_equation_without_equals(self):
        result = await handle_solve_equation({"equation": "x**2 - 9", "variable": "x"})
        assert len(result) == 1
        assert "Solutions for x:" in result[0].text
    
    @pytest.mark.asyncio
    async def test_default_variable(self):
        result = await handle_solve_equation({"equation": "x - 5 = 0"})
        assert len(result) == 1
        assert "Solutions for x: 5" in result[0].text
    
    @pytest.mark.asyncio
    async def test_empty_equation(self):
        result = await handle_solve_equation({"equation": ""})
        assert len(result) == 1
        assert "Error: No equation provided" in result[0].text
    
    @pytest.mark.asyncio
    async def test_no_solution(self):
        result = await handle_solve_equation({"equation": "0*x = 5", "variable": "x"})
        assert len(result) == 1
        # Should handle no solution case


class TestDerivative:
    """Tests for derivative tool"""
    
    @pytest.mark.asyncio
    async def test_polynomial_derivative(self):
        result = await handle_derivative({"expression": "x**2 + 3*x + 2", "variable": "x"})
        assert len(result) == 1
        assert "Derivative of" in result[0].text
        assert "2*x + 3" in result[0].text
    
    @pytest.mark.asyncio
    async def test_trigonometric_derivative(self):
        result = await handle_derivative({"expression": "sin(x)", "variable": "x"})
        assert len(result) == 1
        assert "cos(x)" in result[0].text
    
    @pytest.mark.asyncio
    async def test_exponential_derivative(self):
        result = await handle_derivative({"expression": "exp(x)", "variable": "x"})
        assert len(result) == 1
        assert "exp(x)" in result[0].text
    
    @pytest.mark.asyncio
    async def test_default_variable(self):
        result = await handle_derivative({"expression": "x**3"})
        assert len(result) == 1
        assert "3*x**2" in result[0].text
    
    @pytest.mark.asyncio
    async def test_empty_expression(self):
        result = await handle_derivative({"expression": ""})
        assert len(result) == 1
        assert "Error: No expression provided" in result[0].text


class TestIntegral:
    """Tests for integral tool"""
    
    @pytest.mark.asyncio
    async def test_polynomial_integral(self):
        result = await handle_integral({"expression": "x**2", "variable": "x"})
        assert len(result) == 1
        assert "Integral of" in result[0].text
        assert "x**3/3" in result[0].text
    
    @pytest.mark.asyncio
    async def test_trigonometric_integral(self):
        result = await handle_integral({"expression": "sin(x)", "variable": "x"})
        assert len(result) == 1
        assert "-cos(x)" in result[0].text
    
    @pytest.mark.asyncio
    async def test_constant_integral(self):
        result = await handle_integral({"expression": "5", "variable": "x"})
        assert len(result) == 1
        assert "5*x" in result[0].text
    
    @pytest.mark.asyncio
    async def test_default_variable(self):
        result = await handle_integral({"expression": "x"})
        assert len(result) == 1
        assert "x**2/2" in result[0].text
    
    @pytest.mark.asyncio
    async def test_empty_expression(self):
        result = await handle_integral({"expression": ""})
        assert len(result) == 1
        assert "Error: No expression provided" in result[0].text


class TestMatrixOperations:
    """Tests for matrix_operations tool"""
    
    @pytest.mark.asyncio
    async def test_matrix_addition(self):
        result = await handle_matrix_operations({
            "operation": "add",
            "matrix_a": "[[1,2],[3,4]]",
            "matrix_b": "[[5,6],[7,8]]"
        })
        assert len(result) == 1
        assert "Matrix add result:" in result[0].text
        assert "[[6, 8], [10, 12]]" in result[0].text
    
    @pytest.mark.asyncio
    async def test_matrix_subtraction(self):
        result = await handle_matrix_operations({
            "operation": "subtract",
            "matrix_a": "[[5,6],[7,8]]",
            "matrix_b": "[[1,2],[3,4]]"
        })
        assert len(result) == 1
        assert "Matrix subtract result:" in result[0].text
    
    @pytest.mark.asyncio
    async def test_matrix_multiplication(self):
        result = await handle_matrix_operations({
            "operation": "multiply",
            "matrix_a": "[[1,2],[3,4]]",
            "matrix_b": "[[2,0],[1,2]]"
        })
        assert len(result) == 1
        assert "Matrix multiply result:" in result[0].text
    
    @pytest.mark.asyncio
    async def test_matrix_transpose(self):
        result = await handle_matrix_operations({
            "operation": "transpose",
            "matrix_a": "[[1,2,3],[4,5,6]]"
        })
        assert len(result) == 1
        assert "Transpose result:" in result[0].text
        assert "[[1, 4], [2, 5], [3, 6]]" in result[0].text
    
    @pytest.mark.asyncio
    async def test_matrix_determinant(self):
        result = await handle_matrix_operations({
            "operation": "determinant",
            "matrix_a": "[[1,2],[3,4]]"
        })
        assert len(result) == 1
        assert "Determinant:" in result[0].text
        assert "-2" in result[0].text
    
    @pytest.mark.asyncio
    async def test_matrix_inverse(self):
        result = await handle_matrix_operations({
            "operation": "inverse",
            "matrix_a": "[[1,2],[3,4]]"
        })
        assert len(result) == 1
        assert "Inverse result:" in result[0].text
    
    @pytest.mark.asyncio
    async def test_determinant_non_square_matrix(self):
        result = await handle_matrix_operations({
            "operation": "determinant",
            "matrix_a": "[[1,2,3],[4,5,6]]"
        })
        assert len(result) == 1
        assert "Error: Determinant requires a square matrix" in result[0].text
    
    @pytest.mark.asyncio
    async def test_missing_second_matrix(self):
        result = await handle_matrix_operations({
            "operation": "add",
            "matrix_a": "[[1,2],[3,4]]"
        })
        assert len(result) == 1
        assert "Error:" in result[0].text
        assert "requires two matrices" in result[0].text
    
    @pytest.mark.asyncio
    async def test_missing_operation(self):
        result = await handle_matrix_operations({
            "operation": "",
            "matrix_a": "[[1,2],[3,4]]"
        })
        assert len(result) == 1
        assert "Error:" in result[0].text


class TestStatisticsCalculator:
    """Tests for statistics_calculator tool"""
    
    @pytest.mark.asyncio
    async def test_mean_calculation(self):
        result = await handle_statistics_calculator({
            "data": "[1,2,3,4,5]",
            "operation": "mean"
        })
        assert len(result) == 1
        assert "Statistical mean" in result[0].text
        assert "3.0" in result[0].text
    
    @pytest.mark.asyncio
    async def test_median_calculation(self):
        result = await handle_statistics_calculator({
            "data": "[1,2,3,4,5]",
            "operation": "median"
        })
        assert len(result) == 1
        assert "Statistical median" in result[0].text
        assert "3" in result[0].text
    
    @pytest.mark.asyncio
    async def test_std_calculation(self):
        result = await handle_statistics_calculator({
            "data": "[1,2,3,4,5]",
            "operation": "std"
        })
        assert len(result) == 1
        assert "Statistical std" in result[0].text
    
    @pytest.mark.asyncio
    async def test_min_calculation(self):
        result = await handle_statistics_calculator({
            "data": "[5,2,8,1,9]",
            "operation": "min"
        })
        assert len(result) == 1
        assert "Statistical min" in result[0].text
        assert "1.0" in result[0].text
    
    @pytest.mark.asyncio
    async def test_max_calculation(self):
        result = await handle_statistics_calculator({
            "data": "[5,2,8,1,9]",
            "operation": "max"
        })
        assert len(result) == 1
        assert "Statistical max" in result[0].text
        assert "9.0" in result[0].text
    
    @pytest.mark.asyncio
    async def test_sum_calculation(self):
        result = await handle_statistics_calculator({
            "data": "[1,2,3,4,5]",
            "operation": "sum"
        })
        assert len(result) == 1
        assert "Statistical sum" in result[0].text
        assert "15.0" in result[0].text
    
    @pytest.mark.asyncio
    async def test_variance_calculation(self):
        result = await handle_statistics_calculator({
            "data": "[1,2,3,4,5]",
            "operation": "var"
        })
        assert len(result) == 1
        assert "Statistical var" in result[0].text
    
    @pytest.mark.asyncio
    async def test_mode_calculation(self):
        result = await handle_statistics_calculator({
            "data": "[1,2,2,3,4]",
            "operation": "mode"
        })
        assert len(result) == 1
        assert "Statistical mode" in result[0].text
        assert "2" in result[0].text
    
    @pytest.mark.asyncio
    async def test_empty_data(self):
        result = await handle_statistics_calculator({
            "data": "",
            "operation": "mean"
        })
        assert len(result) == 1
        assert "Error:" in result[0].text
    
    @pytest.mark.asyncio
    async def test_invalid_operation(self):
        result = await handle_statistics_calculator({
            "data": "[1,2,3]",
            "operation": "invalid_op"
        })
        assert len(result) == 1
        assert "Error: Unknown statistical operation" in result[0].text
    
    @pytest.mark.asyncio
    async def test_non_list_data(self):
        result = await handle_statistics_calculator({
            "data": "123",
            "operation": "mean"
        })
        assert len(result) == 1
        assert "Error:" in result[0].text


class TestListTools:
    """Tests for list_tools function"""
    
    @pytest.mark.asyncio
    async def test_list_tools_returns_all_tools(self):
        tools = await list_tools()
        assert len(tools) == 6
        
        tool_names = [tool.name for tool in tools]
        assert "calculate_expression" in tool_names
        assert "solve_equation" in tool_names
        assert "derivative" in tool_names
        assert "integral" in tool_names
        assert "matrix_operations" in tool_names
        assert "statistics_calculator" in tool_names
    
    @pytest.mark.asyncio
    async def test_tools_have_descriptions(self):
        tools = await list_tools()
        for tool in tools:
            assert tool.description is not None
            assert len(tool.description) > 0
    
    @pytest.mark.asyncio
    async def test_tools_have_input_schemas(self):
        tools = await list_tools()
        for tool in tools:
            assert tool.inputSchema is not None
            assert "type" in tool.inputSchema
            assert "properties" in tool.inputSchema


class TestCallTool:
    """Tests for call_tool dispatcher"""
    
    @pytest.mark.asyncio
    async def test_call_calculate_expression(self):
        result = await call_tool("calculate_expression", {"expression": "2+2"})
        assert len(result) == 1
        assert "Result: 4" in result[0].text
    
    @pytest.mark.asyncio
    async def test_call_solve_equation(self):
        result = await call_tool("solve_equation", {"equation": "x - 5 = 0"})
        assert len(result) == 1
        assert "Solutions" in result[0].text
    
    @pytest.mark.asyncio
    async def test_call_derivative(self):
        result = await call_tool("derivative", {"expression": "x**2"})
        assert len(result) == 1
        assert "Derivative" in result[0].text
    
    @pytest.mark.asyncio
    async def test_call_integral(self):
        result = await call_tool("integral", {"expression": "x"})
        assert len(result) == 1
        assert "Integral" in result[0].text
    
    @pytest.mark.asyncio
    async def test_call_matrix_operations(self):
        result = await call_tool("matrix_operations", {
            "operation": "transpose",
            "matrix_a": "[[1,2],[3,4]]"
        })
        assert len(result) == 1
        assert "Transpose" in result[0].text
    
    @pytest.mark.asyncio
    async def test_call_statistics_calculator(self):
        result = await call_tool("statistics_calculator", {
            "data": "[1,2,3]",
            "operation": "mean"
        })
        assert len(result) == 1
        assert "Statistical mean" in result[0].text
    
    @pytest.mark.asyncio
    async def test_call_unknown_tool(self):
        result = await call_tool("unknown_tool", {})
        assert len(result) == 1
        assert "Unknown tool" in result[0].text


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=math_mcp_server", "--cov-report=term-missing"])

# Made with Bob
