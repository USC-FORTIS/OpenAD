from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
import re
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from entity.code_quality import CodeQuality
import subprocess
from datetime import datetime, timedelta
import json
from filelock import FileLock
from openai import OpenAI
import os
from config.config import Config
os.environ['OPENAI_API_KEY'] = Config.OPENAI_API_KEY

# Initialize OpenAI LLM
llm = ChatOpenAI(model="gpt-4o", temperature=0)

template_pyod = PromptTemplate.from_template("""
You are an expert Python developer with deep experience in anomaly detection libraries. Your task is to:

1. Use the provided official documentation content for `{algorithm}` to understand how to use the specified algorithm class, including initialization, training, and prediction methods.
2. Write only executable Python code for anomaly detection using PyOD and do not include any explanations or descriptions.
3. Base your code strictly on the following official documentation excerpt:

--- BEGIN DOCUMENTATION ---
{algorithm_doc}
--- END DOCUMENTATION ---

4. The code should:
   (1) import sys, os and include command `sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))` in the head
   (2) import DataLoader using following commend `from data_loader.data_loader import DataLoader` after (1)
   (3) Initialize DataLoader using statement `dataloader_train = DataLoader(filepath = {data_path_train}, store_script=True, store_path = 'train_data_loader.py')` & `dataloader_test = DataLoader(filepath = {data_path_test}, store_script=True, store_path = 'test_data_loader.py')`
   (4) Use the statement `X_train, y_train = dataloader_train.load_data(split_data=False)` & `X_test, y_test = dataloader_train.load_data(split_data=False)` to generate variables X_train, y_train, X_test, y_test; 
   (5) Initialize the specified algorithm `{algorithm}` strictly following the provided documentation and train the model with `X_train`
   (6) Determine whether the following parameters `{parameters}` apply to this initialization function and, if so, add their values ​to the function.
   (7) Use `.decision_scores_` on `X_train` for training outlier scores
       Use `.decision_function(X_test)` for test outlier scores
       Calculate AUROC (Area Under the Receiver Operating Characteristic Curve) and AUPRC (Area Under the Precision-Recall Curve) based on given data
   (8) Using variables to record the AUROC & AUPRC and print them out in following format:
       AUROC:\s*(\d+.\d+)
       AUPRC:\s*(\d+.\d+)
   (9) Using variables to record prediction failed data and print these points out with true label in following format:
       `Failed prediction at point [xx,xx,xx...] with true label xx` Use `.tolist()` to convert point to be an array.
                     

IMPORTANT: 
- Strictly follow steps (2)-(8) to load the data from `{data_path_train}` & {data_path_test}.
- Do NOT input optional or incorrect parameters.
""")

template_pygod = PromptTemplate.from_template("""
You are an expert Python developer with deep experience in anomaly detection libraries. Your task is to:

1. Use the provided official documentation content for `{algorithm}` to understand how to use the specified algorithm class, including initialization, training, and prediction methods.
2. Write only executable Python code for anomaly detection using PyGOD and do not include any explanations or descriptions.
3. Base your code strictly on the following official documentation excerpt:

--- BEGIN DOCUMENTATION ---
{algorithm_doc}
--- END DOCUMENTATION ---

4. The code should:
   (1) Import sys, os, torch, and include the command `sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))`&`from pygod.detector import {algorithm}`
   (2) Load training and test data using `torch.load` with parameter `weights_only=False` from the file paths `{data_path_train}` and `{data_path_test}` respectively.
   (3) Convert labels in the loaded data by executing:
       `train_data.y = (train_data.y != 0).long()`
       `test_data.y = (test_data.y != 0).long()`
   (4) Initialize the specified algorithm `{algorithm}` with the provided parameters `{parameters}` (if applicable) strictly following the documentation excerpt.
   (5) Train the model using `model.fit(train_data)`.
   (6) Predict on the test data using `pred, score = model.predict(test_data, return_score=True)`.
   (7) Extract the true labels and corresponding scores using the test mask:
       `true_labels = test_data.y[test_data.test_mask]`
       `score = score[test_data.test_mask]`
   (8) Calculate AUROC using `roc_auc_score` and AUPRC using `average_precision_score` from sklearn.metrics.
   (9) Print the AUROC and AUPRC in the following format:
       AUROC:\s*(\d+.\d+)
       AUPRC:\s*(\d+.\d+)

IMPORTANT:
- Strictly follow steps (2)-(9) to load the data from `{data_path_train}` and `{data_path_test}`.
- Do NOT include any additional or incorrect parameters.
""")


template_fix = PromptTemplate.from_template("""
You are an expert Python developer with deep experience in anomaly detection libraries.

Here is the original code that raised an error:
--- Original Code ---
{code}

--- Error Message ---
{error_message}

Official documentation for `{algorithm}`:
--- BEGIN DOCUMENTATION ---
{algorithm_doc}
--- END DOCUMENTATION ---

Task:
1. Analyse the error and fix it strictly according to the doc.
2. Output **executable** Python ONLY, no comments/explanations.
""")

# ---------- CLASS ----------
class AgentCoder:
    """Now responsible for code generation **and** modification."""
    def __init__(self):
        pass

    # -------- generation --------
    def generate_code(
        self,
        algorithm,
        data_path_train,
        data_path_test,
        algorithm_doc,
        input_parameters,
        package_name
    ) -> str:
        tpl = template_pyod if package_name == "pyod" else template_pygod
        raw = llm.invoke(
            tpl.invoke({
                "algorithm": algorithm,
                "data_path_train": data_path_train,
                "data_path_test": data_path_test,
                "algorithm_doc": algorithm_doc,
                "parameters": str(input_parameters)
            })
        ).content
        return self._clean(raw)

    # -------- revision (moved from old Reviewer) --------
    def revise_code(self, code_quality: CodeQuality, algorithm_doc: str) -> str:
        fixed = llm.invoke(
            template_fix.invoke({
                "code": code_quality.code,
                "error_message": code_quality.error_message,
                "algorithm": code_quality.algorithm,
                "algorithm_doc": algorithm_doc
            })
        ).content
        # increase review counter here
        code_quality.review_count += 1
        return self._clean(fixed)

    # -------- util --------
    @staticmethod
    def _clean(code: str) -> str:
        code = re.sub(r"```(python)?", "", code)
        return re.sub(r"```", "", code).strip()

if __name__ == "__main__":
   agentCoder = AgentCoder()
   from agents.agent_selector import AgentSelector
   from agents.agent_infominer import AgentInfoMiner
   user_input = {
      "algorithm": ["CARD"],
      "dataset_train": "./data/inj_cora_train.pt",
      "dataset_test": "./data/inj_cora_test.pt",
      "parameters": {}
   }
   agentSelector = AgentSelector(user_input=user_input)# if want to unit test, please import AgentSelector
   AgentInfominer = AgentInfoMiner()
   algorithm_doc = AgentInfoMiner.query_docs(algorithm=agentSelector.tools[0], vectorstore=agentSelector.vectorstore, package_name=agentSelector.package_name)

   code = agentCoder.generate_code(
      algorithm=user_input["algorithm"][0],
      data_path_train=user_input["dataset_train"],
      data_path_test=user_input["dataset_test"],
      algorithm_doc=algorithm_doc,
      input_parameters=user_input["parameters"],
      package_name=agentSelector.package_name
   )

   print(code)
