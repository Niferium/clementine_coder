import mlx.core as mx
from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler, make_logits_processors
import json
from typing import Dict, Any, List
import src.prompts.sys_prompt as sys_prompt
import logging
import gc

class EvaluationAgent:
    """
    A class that evaluates builder agent responses using Qwen3-Coder-30B model.
    """
    
    def __init__(self):
        """
        Initialize the evaluation agent with Qwen3-Coder-30B model.
        
        Args:
            model_path: Path to the Qwen3-Coder-30B model
            max_tokens: Maximum tokens for generation
        """
        self.system_prompt = sys_prompt.SYSTEM_PROMPT_EVALUATION_AGENT()

    def _refreshModel(self, model_name: str):
        # Loads the specified model, unloading any previously loaded model to free up memory. If the requested model is already loaded, it simply returns it.

        if self._loaded_name == model_name:
            return self._loaded_model, self._loaded_tokenizer

        if self._loaded_model is not None:
            print(f"   🔄 Unloading {self._loaded_name}...")
            self._loaded_model     = None
            self._loaded_tokenizer = None
            self._loaded_name      = None
            gc.collect()
            mx.metal.clear_cache()

        print(f"   📦 Loading {model_name}...")
        self._loaded_model, self._loaded_tokenizer = load(model_name)
        self._loaded_name = model_name
        return self._loaded_model, self._loaded_tokenizer
        
    def evaluate_response(
            self,
            builder_response: str,
            _loaded_model,
            _loaded_tokenizer
    ) -> Dict[str, Any]:
        """
        Evaluate the builder's response and provide detailed feedback.
        
        Args:
            builder_response: The response from the builder agent
            requirements: Optional requirements to consider during evaluation
            
        Returns:
            Dictionary containing evaluation results and feedback
        """

        conversation = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Evaluate this response by a coding agent:\n{builder_response}"}
        ]
        prompt = _loaded_tokenizer.apply_chat_template(conversation, add_generation_prompt=True)

        sampler = make_sampler(temp=0.3, top_p=0.9)
        logits_processors = make_logits_processors(repetition_penalty=1.3)

        # Generate response using the model
        response = generate(
            _loaded_model, 
            _loaded_tokenizer, 
            prompt, 
            max_tokens=1024,
            verbose=True,
            sampler = sampler,
            logits_processors = logits_processors
        )

        # Parse the evaluation results
        evaluation_result = self._parse_evaluation(response)

        # Get pass/fail + score — guard against bad JSON from model
        try:
            parsed_json = json.loads(response)
            pass_fail, score = self.check_json_score(parsed_json)
            
            # Merge issues from the model's raw JSON output
            evaluation_result["issues"] = parsed_json.get("issues", [])
            evaluation_result["verdict"] = parsed_json.get("verdict", "")
            evaluation_result["fixes"] = parsed_json.get("fixes", "")
        except (ValueError, TypeError) as e:
            print(f"[EvaluationAgent] check_json_score failed: {e}. Defaulting to fail.")
            pass_fail, score = "fail", 0.0
            evaluation_result["issues"] = parsed_json.get("issues", [])

        print(f"debug# check if pass or fail {pass_fail}, score: {score}")

        # Return everything in one dict
        evaluation_result["pass_fail"] = pass_fail
        evaluation_result["score"] = score
        print(f"debug# evaluation_result {evaluation_result}")

        return evaluation_result
    
    def check_json_score(self, json_data):
        """
        Check if the JSON contains a score and determine pass/fail status.
        
        Args:
            json_data (str or dict): JSON string or parsed dictionary containing score and issues
            
        Returns:
            tuple: (pass_fail_status, score) 
                where pass_fail_status is "pass" or "fail"
                and score is the numeric score value
        """
        # Handle string JSON data by parsing it
        if isinstance(json_data, str):
            try:
                parsed_data = json.loads(json_data)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON data: {e}")
        else:
            parsed_data = json_data
        
        # Extract score with default value
        score = parsed_data.get("score", 0.0)
        
        # Validate score is numeric
        if not isinstance(score, (int, float)):
            raise TypeError(f"Score must be numeric, got {type(score)}")
        
        # Validate score is within valid range (0-1)
        if not 0 <= score <= 1:
            # Log warning for out-of-range scores but continue processing
            pass # Could add logging here if needed
        
        # Determine pass/fail based on score threshold
        pass_fail = "pass" if score >= 0.7 else "fail"
    
        return (pass_fail, score)

# Example usage:
# json_data = {
#     "score": 0.65,
#     "issues": [
#         "Missing error handling",
#         "No explanation of how to run the code", 
#         "Not a complete solution for displaying 'Hello World'",
#     "Missing error handling"
# },
#     "verdict": "retry"
# }
# 
# status, score = check_json_score(json_data)
# print(f"Status: {status}, Score: {score}")
    
    def _parse_evaluation(self, evaluation_text: str) -> Dict[str, Any]:
        """
        Parse the evaluation text into structured data.
        
        Args:
            evaluation_text: Text containing evaluation results
            
        Returns:
            Dictionary with parsed evaluation data
        """
        # Simple parsing logic - in a real implementation, you'd want more robust parsing
        evaluation_data = {
            "overall_score": 0,
            "strengths": [],
            "areas_for_improvement": [],
            "recommendations": [],
            "code_quality_score": 0,
            "functionality_score": 0,
    "documentation_score": 0
        }
        
        # Extract scores and sections
        lines = evaluation_text.split('\n')
        for line in lines:
            if "Overall Score" in line:
                try:
                    score = int(line.split(":")[1].strip())
                    evaluation_data["overall_score"] = score
                except:
                    pass
            elif "Strengths:" in line:
                # Extract strengths from the line
                strength_line = line.split("Strengths:")[1].strip()
                if strength_line.startswith("-"):
                    strengths = strength_line.split("-")[1:]
                    evaluation_data["strengths"] = [s.strip() for s in strengths if s.strip()]
                else:
                    evaluation_data["strengths"] = [strength_line]
            elif "Areas for improvement:" in line:
                # Extract areas for improvement
                improvement_line = line.split("Areas for improvement:")[1].strip()
                if improvement_line.startswith("-"):
                    improvements = improvement_line.split("-")[1:]
                    evaluation_data["areas_for_improvement"] = [i.strip() for i in improvements if i.strip()]
                else:
                    evaluation_data["areas_for_improvement"] = [improvement_line]
            elif "Specific recommendations:" in line:
                recommendation_line = line.split("Specific recommendations:")[1].strip()
                if recommendation_line.startswith("-"):
                    recommendations = recommendation_line.split("-")[1:]
                    evaluation_data["recommendations"] = [r.strip() for r in recommendations if r.strip()]
                else:
                    evaluation_data["recommendations"] = [recommendation_line]
        
        return evaluation_data
    
    # def generate_documentation(self, evaluation_result: Dict[str, Any]) -> str:
    #     """
    #     Generate formatted documentation from evaluation results.
        
    #     Args:
    #         evaluation_result: Dictionary containing evaluation data
            
    #     Returns:
    #         Formatted documentation string
    #     """
    #     doc = f"""
    #     Evaluation Report
    #     =================

    #     Overall Score: {evaluation_result.get('overall_score', 0)/10*100}% 
    #     Score: {evaluation_result.get('overall_score', 0)/10*100}% (out of 100)

    #     Strengths:
    #     {'\n'.join([f"- {strength}" for strength in evaluation_result.get('strengths', [])])}

    #     Areas for Improvement:
    #     {'\n'.'} 
    #     """